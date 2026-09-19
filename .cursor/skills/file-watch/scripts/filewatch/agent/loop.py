from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filewatch.agent.logging import ToolCallLogger
from filewatch.agent.registry import ToolRegistry
from filewatch.agent.sandbox import default_protected_roots
from filewatch.agent.tools import build_default_registry
from filewatch.agent.types import ToolCall, ToolContext
from filewatch.llm import LlmError, chat_messages
from filewatch.models import DEFAULT_AGENT_MAX_STEPS, DEFAULT_AGENT_TIMEOUT_SECONDS, FileEvent
from filewatch.paths import to_posix

SYSTEM_PROMPT = """你是 filewatch 内置智能体，在指定工作区内完成用户任务。
规则：
- 工作区路径见用户消息；所有文件读写必须相对该工作区。
- 优先使用 Read / Glob / Grep / Write；需要 shell 时再用 Bash 或 PowerShell。
- 禁止删除工作区根目录、FILEWATCH_HOME 或 filewatch 自身。
- 不要编造未读过的文件内容；先读再改。
- 完成后用简短中文总结做了什么。
"""


@dataclass
class AgentRunResult:
    status: str  # ok | error
    output: str
    error: str | None = None
    message: str | None = None
    steps: int = 0
    tool_calls: int = 0
    log_path: str | None = None
    last_reply: str = ""


def _parse_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    raw = message.get("tool_calls") or []
    if not isinstance(raw, list):
        return []
    calls: list[ToolCall] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or {}
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "")
        call_id = str(item.get("id") or f"call_{index}")
        args_raw = fn.get("arguments") or "{}"
        arguments: dict[str, Any]
        if isinstance(args_raw, dict):
            arguments = args_raw
        elif isinstance(args_raw, str):
            try:
                parsed = json.loads(args_raw or "{}")
                arguments = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                arguments = {"_raw": args_raw}
        else:
            arguments = {}
        if name:
            calls.append(ToolCall(id=call_id, name=name, arguments=arguments))
    return calls


def _assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
    """Normalize assistant message for next round (keep tool_calls shape)."""
    out: dict[str, Any] = {"role": "assistant"}
    content = message.get("content")
    if content is not None:
        out["content"] = content
    tool_calls = message.get("tool_calls")
    if tool_calls:
        out["tool_calls"] = tool_calls
    return out


def run_builtin_agent(
    *,
    prompt: str,
    event: FileEvent,
    workspace: Path,
    job_id: str,
    log_dir: Path,
    timeout_seconds: float = DEFAULT_AGENT_TIMEOUT_SECONDS,
    max_steps: int = DEFAULT_AGENT_MAX_STEPS,
    model: str | None = None,
    suppress: Callable[[str, float], None] | None = None,
    registry: ToolRegistry | None = None,
    chat: Callable[..., dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
) -> AgentRunResult:
    workspace = workspace.resolve()
    registry = registry or build_default_registry()
    chat_fn = chat or chat_messages
    log_path = log_dir / f"{job_id}.jsonl"
    logger = ToolCallLogger(log_path, job_id=job_id, meta=meta)
    result: AgentRunResult | None = None
    ctx = ToolContext(
        workspace=workspace,
        job_id=job_id,
        watch_id=event.watch_id,
        suppress=suppress,
        protected_roots=default_protected_roots(workspace),
    )
    user_blob = {
        "task": prompt,
        "workspace": to_posix(workspace),
        "event": event.to_dict(),
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "请根据任务要求处理文件变化。上下文 JSON：\n"
                + json.dumps(user_blob, ensure_ascii=False, indent=2)
            ),
        },
    ]
    tools = registry.openai_tools()
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    steps = 0
    tool_call_count = 0
    final_text = ""
    trigger = f"{event.type} {to_posix(event.path)}"
    logger.emit("system", text="内置智能体启动", session_start=True)
    logger.emit("system", text=f"任务要求：{prompt}", source="user")
    logger.emit("system", text=f"工作区 {to_posix(workspace)} · 触发 {trigger}")

    try:
        while steps < max_steps:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result = AgentRunResult(
                    status="error",
                    output=final_text[-4000:],
                    error="timeout",
                    message="智能体任务超时",
                    steps=steps,
                    tool_calls=tool_call_count,
                    log_path=str(log_path),
                )
                return result
            try:
                message = chat_fn(
                    messages,
                    tools=tools,
                    model=model,
                    timeout=min(120.0, max(5.0, remaining)),
                )
            except LlmError as exc:
                result = AgentRunResult(
                    status="error",
                    output=final_text[-4000:],
                    error=exc.error,
                    message=exc.message,
                    steps=steps,
                    tool_calls=tool_call_count,
                    log_path=str(log_path),
                )
                return result
            steps += 1
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                final_text = content.strip()
                logger.emit("agent", text=final_text)
            calls = _parse_tool_calls(message)
            messages.append(_assistant_message_for_history(message))
            if not calls:
                last_reply = content.strip() if isinstance(content, str) and content.strip() else ""
                result = AgentRunResult(
                    status="ok",
                    output=(last_reply or final_text or "（无输出）")[-4000:],
                    steps=steps,
                    tool_calls=tool_call_count,
                    log_path=str(log_path),
                    last_reply=last_reply[-4000:] if last_reply else "",
                )
                return result
            records = registry.dispatch(calls, ctx, logger=logger)
            tool_call_count += len(records)
            for record in records:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": record.id,
                        "content": record.result.to_content(),
                    }
                )

        result = AgentRunResult(
            status="error",
            output=(final_text or f"超过 max_steps={max_steps}")[-4000:],
            error="max_steps",
            message=f"超过最大步数 {max_steps}",
            steps=steps,
            tool_calls=tool_call_count,
            log_path=str(log_path),
        )
        return result
    finally:
        if result is None:
            result = AgentRunResult(
                status="error",
                output=final_text[-4000:] if final_text else "",
                error="aborted",
                message="智能体已中断",
                steps=steps,
                tool_calls=tool_call_count,
                log_path=str(log_path),
            )
        if result.status == "ok":
            logger.close("ok", f"已完成，共 {result.steps} 步 · 工具 {result.tool_calls} 次")
        else:
            logger.close(result.error or result.status, result.message or result.error or "失败")
