"""把内部的 Chat Completions 形状转成 Anthropic Messages，再转回。"""

from __future__ import annotations

import json
from typing import Any

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 8192
_STOP_REASON = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "pause_turn": "stop",
    "refusal": "stop",
    "tool_use": "tool_calls",
    "max_tokens": "length",
}


def is_anthropic_wire(wire_api: str | None) -> bool:
    return (wire_api or "").strip().lower() in {"anthropic", "messages", "claude"}


def anthropic_url(base_url: str) -> str:
    return (base_url or "").rstrip("/") + "/messages"


def anthropic_headers(api_key: str) -> dict[str, str]:
    """官方 Claude 用 x-api-key；不少网关只认 Bearer。两个都带上。"""
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": ANTHROPIC_VERSION,
    }
    key = (api_key or "").strip()
    if key:
        headers["x-api-key"] = key
        headers["Authorization"] = f"Bearer {key}"
    return headers


def openai_tools_to_anthropic(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in tools or []:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else item
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        schema = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else None
        if not schema:
            schema = {"type": "object", "properties": {}}
        else:
            schema = dict(schema)
            schema.setdefault("type", "object")
            if schema.get("type") == "object":
                schema.setdefault("properties", {})
        out.append(
            {
                "name": name,
                "description": str(fn.get("description") or ""),
                "input_schema": schema,
            }
        )
    return out


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str) and part:
                parts.append(part)
            elif isinstance(part, dict):
                text = str(part.get("text") or part.get("content") or "")
                if text:
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _as_blocks(content: Any) -> list[dict[str, Any]]:
    if content is None or content == "":
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for part in content:
            if isinstance(part, str) and part:
                blocks.append({"type": "text", "text": part})
            elif isinstance(part, dict) and part.get("type"):
                blocks.append(part)
            elif isinstance(part, dict):
                text = str(part.get("text") or part.get("content") or "")
                if text:
                    blocks.append({"type": "text", "text": text})
        return blocks
    return [{"type": "text", "text": str(content)}]


def _merge_content(left: Any, right: Any) -> Any:
    merged = _as_blocks(left) + _as_blocks(right)
    if not merged:
        return ""
    if all(b.get("type") == "text" for b in merged):
        return "\n\n".join(str(b.get("text") or "") for b in merged if b.get("text"))
    return merged


def _parse_tool_input(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _assistant_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = _as_blocks(message.get("content"))
    for tc in message.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = str(fn.get("name") or "").strip()
        tool_id = str(tc.get("id") or name or "tool")
        blocks.append(
            {
                "type": "tool_use",
                "id": tool_id,
                "name": name,
                "input": _parse_tool_input(fn.get("arguments")),
            }
        )
    return [b for b in blocks if b.get("type") != "text" or (b.get("text") or "").strip()]


def _has_payload(content: Any) -> bool:
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return bool(content)
    return bool(content)


def _ensure_alternating(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant"):
            continue
        if not _has_payload(content):
            continue
        if out and out[-1].get("role") == role:
            out[-1]["content"] = _merge_content(out[-1].get("content"), content)
        else:
            out.append({"role": role, "content": content})
    if out and out[0].get("role") != "user":
        out.insert(0, {"role": "user", "content": "(continue)"})
    if not out:
        out.append({"role": "user", "content": "(empty)"})
    return out


def openai_messages_to_anthropic(
    messages: list[dict[str, Any]] | None,
) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for raw in messages or []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip()
        if role == "system":
            text = _content_to_text(raw.get("content")).strip()
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": str(raw.get("tool_call_id") or raw.get("id") or "tool"),
                "content": _content_to_text(raw.get("content")) or "",
            }
            if converted and converted[-1].get("role") == "user":
                converted[-1]["content"] = _merge_content(converted[-1].get("content"), [block])
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        if role == "assistant":
            blocks = _assistant_blocks(raw)
            if not blocks:
                continue
            if all(b.get("type") == "text" for b in blocks):
                converted.append(
                    {
                        "role": "assistant",
                        "content": "\n".join(str(b.get("text") or "") for b in blocks if b.get("text")),
                    }
                )
            else:
                converted.append({"role": "assistant", "content": blocks})
            continue
        if role == "user":
            text = _content_to_text(raw.get("content"))
            if not text.strip():
                continue
            converted.append({"role": "user", "content": text})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, _ensure_alternating(converted)


def build_anthropic_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    system, converted = openai_messages_to_anthropic(messages)
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max(1, int(max_tokens)),
        "messages": converted,
    }
    if system:
        body["system"] = system
    converted_tools = openai_tools_to_anthropic(tools)
    if converted_tools:
        body["tools"] = converted_tools
    if temperature is not None:
        body["temperature"] = temperature
    return body


def _map_stop_reason(reason: Any) -> str | None:
    if reason is None or reason == "":
        return None
    text = str(reason)
    return _STOP_REASON.get(text, text)


def _usage_from_anthropic(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    prompt = int(src.get("input_tokens") or src.get("prompt_tokens") or 0)
    completion = int(src.get("output_tokens") or src.get("completion_tokens") or 0)
    cached = int(src.get("cache_read_input_tokens") or src.get("cached_tokens") or 0)
    usage: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }
    if cached:
        usage["cached_tokens"] = cached
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return usage


def anthropic_message_to_openai(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"choices": [{"index": 0, "finish_reason": None, "message": {"role": "assistant", "content": None}}]}
    if isinstance(data.get("choices"), list):
        return data
    payload = data.get("message") if isinstance(data.get("message"), dict) and data.get("type") == "message_start" else data
    content_blocks = payload.get("content") if isinstance(payload.get("content"), list) else []
    texts: list[str] = []
    reasoning: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for i, block in enumerate(content_blocks):
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            texts.append(str(block.get("text") or ""))
        elif btype == "tool_use":
            inp = block.get("input") if isinstance(block.get("input"), dict) else {}
            tool_calls.append(
                {
                    "id": str(block.get("id") or f"toolu_{i}"),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": json.dumps(inp, ensure_ascii=False),
                    },
                }
            )
        elif btype in ("thinking", "redacted_thinking"):
            thinking = str(block.get("thinking") or block.get("content") or "")
            if thinking:
                reasoning.append(thinking)
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(texts) or None,
    }
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage_src = payload.get("usage") if isinstance(payload.get("usage"), dict) else data.get("usage")
    return {
        "id": payload.get("id") or data.get("id"),
        "model": payload.get("model") or data.get("model"),
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": _map_stop_reason(payload.get("stop_reason") or data.get("stop_reason")),
                "message": message,
            }
        ],
        "usage": _usage_from_anthropic(usage_src if isinstance(usage_src, dict) else {}),
    }
