from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

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
from filewatch.settings import DEFAULT_WIRE_API, load_llm_config, parse_wire_api


class LlmError(Exception):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


def _open_json(request: urllib.request.Request, timeout: float) -> Any:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
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


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    payload = _open_json(request, timeout)
    if not isinstance(payload, dict):
        raise LlmError("llm_failed", "LLM 返回格式无法识别")
    return payload


def _get_json(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, method="GET", headers=headers)
    return _open_json(request, timeout)


def parse_llm_models(payload: Any) -> list[dict[str, str]]:
    items: list[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        raw = payload.get("data")
        if raw is None:
            raw = payload.get("models")
        if isinstance(raw, list):
            items = raw
        elif isinstance(payload.get("id") or payload.get("name") or payload.get("model"), str):
            items = [payload]
    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        model_id = ""
        name = ""
        if isinstance(item, str):
            model_id = item.strip()
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
            name = str(item.get("display_name") or item.get("name") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        models.append({"id": model_id, "name": name or model_id})
    models.sort(key=lambda item: item["id"].casefold())
    return models


def _models_url(base_url: str) -> str:
    return (base_url or "").rstrip("/") + "/models"


def _models_headers(api_key: str, wire_api: str) -> dict[str, str]:
    if is_anthropic_wire(wire_api):
        headers = anthropic_headers(api_key)
        headers.pop("Content-Type", None)
        headers["Accept"] = "application/json"
        return headers
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def list_llm_models(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    saved = load_llm_config()

    if "base_url" in data:
        base_url = str(data.get("base_url") or "").strip().rstrip("/")
    else:
        base_url = saved.base_url
    if not base_url:
        return {"ok": False, "error": "bad_request", "message": "base_url 不能为空"}
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"ok": False, "error": "bad_request", "message": "base_url 必须是 http(s) 地址"}

    if "wire_api" in data:
        incoming = data.get("wire_api")
        if incoming is None or incoming == "":
            wire_api = DEFAULT_WIRE_API
        else:
            parsed_wire = parse_wire_api(incoming)
            if parsed_wire is None:
                return {"ok": False, "error": "bad_request", "message": "wire_api 须为 chat、responses 或 anthropic"}
            wire_api = parsed_wire
    else:
        wire_api = saved.wire_api

    incoming_key = data.get("api_key")
    if incoming_key is None:
        api_key = saved.api_key
    elif not isinstance(incoming_key, str):
        return {"ok": False, "error": "bad_request", "message": "api_key 必须是字符串"}
    else:
        api_key = incoming_key.strip() or saved.api_key
    if not api_key:
        return {"ok": False, "error": "llm_not_configured", "message": "请先在设置页填写 LLM API Key"}

    try:
        payload = _get_json(_models_url(base_url), _models_headers(api_key, wire_api), timeout=20)
    except LlmError as exc:
        return {"ok": False, "error": exc.error, "message": exc.message}

    models = parse_llm_models(payload)
    if not models:
        return {"ok": False, "error": "llm_failed", "message": "接口没有返回可用模型"}
    return {"ok": True, "models": models, "message": f"已拉取 {len(models)} 个模型"}


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
