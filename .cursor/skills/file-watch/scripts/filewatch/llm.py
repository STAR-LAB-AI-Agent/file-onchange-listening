from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from filewatch.settings import load_llm_config


class LlmError(Exception):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


def _post_chat(body: dict[str, Any], *, timeout: float, api_key: str, base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        if exc.code in {401, 403}:
            raise LlmError("llm_auth", "LLM API Key 无效或没有权限") from exc
        raise LlmError("llm_failed", f"LLM 请求失败（HTTP {exc.code}）{(': ' + detail) if detail else ''}") from exc
    except TimeoutError as exc:
        raise LlmError("llm_timeout", "LLM 请求超时") from exc
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise LlmError("llm_timeout", "LLM 请求超时") from exc
        raise LlmError("llm_failed", f"无法连接 LLM：{reason}") from exc
    except json.JSONDecodeError as exc:
        raise LlmError("llm_failed", "LLM 返回的不是 JSON") from exc
    if not isinstance(payload, dict):
        raise LlmError("llm_failed", "LLM 返回格式无法识别")
    return payload


def chat_complete(system: str, user: str, *, timeout: float = 45.0) -> str:
    cfg = load_llm_config()
    if not cfg.api_key:
        raise LlmError("llm_not_configured", "请先在设置页填写 LLM API Key")
    payload = _post_chat(
        {
            "model": cfg.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=timeout,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
    )
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError("llm_failed", "LLM 返回格式无法识别") from exc
    if not isinstance(content, str) or not content.strip():
        raise LlmError("llm_failed", "LLM 返回空内容")
    return content


def chat_messages(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    timeout: float = 120.0,
    temperature: float = 0,
) -> dict[str, Any]:
    """OpenAI 兼容 chat/completions，返回 assistant message（含可选 tool_calls）。"""
    cfg = load_llm_config()
    if not cfg.api_key:
        raise LlmError("llm_not_configured", "请先在设置页填写 LLM API Key")
    body: dict[str, Any] = {
        "model": model or cfg.model,
        "temperature": temperature,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    payload = _post_chat(body, timeout=timeout, api_key=cfg.api_key, base_url=cfg.base_url)
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError("llm_failed", "LLM 返回格式无法识别") from exc
    if not isinstance(message, dict):
        raise LlmError("llm_failed", "LLM 返回格式无法识别")
    return message


def test_llm_connection() -> dict[str, Any]:
    try:
        chat_complete(
            '只输出 JSON：{"ok": true}',
            "ping",
            timeout=20,
        )
    except LlmError as exc:
        return {"ok": False, "error": exc.error, "message": exc.message}
    return {"ok": True, "message": "LLM 连接正常"}
