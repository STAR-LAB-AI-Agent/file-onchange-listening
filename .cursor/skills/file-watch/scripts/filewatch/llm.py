from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any

from filewatch.anthropic_compat import (
    anthropic_headers,
    anthropic_message_to_openai,
    anthropic_url,
    build_anthropic_body,
    is_anthropic_wire,
)
from filewatch.responses_compat import (
    build_responses_body,
    is_responses_wire,
    looks_like_responses_payload,
    responses_headers,
    responses_to_openai,
    responses_url,
)
from filewatch.settings import load_llm_config


class LlmError(Exception):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
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


def _to_chat_payload(payload: dict[str, Any], *, wire_api: str) -> dict[str, Any]:
    if isinstance(payload.get("choices"), list):
        return payload
    if is_anthropic_wire(wire_api) or payload.get("type") == "message":
        return anthropic_message_to_openai(payload)
    if is_responses_wire(wire_api) or looks_like_responses_payload(payload):
        return responses_to_openai(payload)
    return payload


def _request_chat(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    timeout: float,
    temperature: float = 0,
) -> dict[str, Any]:
    cfg = load_llm_config()
    if not cfg.api_key:
        raise LlmError("llm_not_configured", "请先在设置页填写 LLM API Key")
    model_name = model or cfg.model
    if is_anthropic_wire(cfg.wire_api):
        url = anthropic_url(cfg.base_url)
        headers = anthropic_headers(cfg.api_key)
        body = build_anthropic_body(
            model=model_name,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )
    elif is_responses_wire(cfg.wire_api):
        url = responses_url(cfg.base_url)
        headers = responses_headers(cfg.api_key)
        body = build_responses_body(
            model=model_name,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )
    else:
        url = f"{cfg.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
        }
        body = {
            "model": model_name,
            "temperature": temperature,
            "messages": messages,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
    payload = _post_json(url, body, headers, timeout)
    return _to_chat_payload(payload, wire_api=cfg.wire_api)


def _assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError("llm_failed", "LLM 返回格式无法识别") from exc
    if not isinstance(message, dict):
        raise LlmError("llm_failed", "LLM 返回格式无法识别")
    return message


def chat_complete(system: str, user: str, *, timeout: float = 45.0) -> str:
    payload = _request_chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        timeout=timeout,
    )
    content = _assistant_message(payload).get("content")
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
    """按设置的协议发请求，返回 OpenAI 形状的 assistant message（含可选 tool_calls）。"""
    payload = _request_chat(
        messages,
        tools=tools,
        model=model,
        timeout=timeout,
        temperature=temperature,
    )
    return _assistant_message(payload)


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
