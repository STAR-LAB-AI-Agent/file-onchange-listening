"""把内部的 Chat Completions 形状转成 OpenAI Responses，再转回。"""

from __future__ import annotations

import json
import re
from typing import Any

_STATUS_FINISH = {
    "incomplete": "length",
    "failed": "stop",
    "cancelled": "stop",
}
_OMIT_TEMP = re.compile(
    r"(?:^|[-./_])(?:o1|o3|o4-mini|gpt-5|deepseek-reasoner|deepseek-r1|kimi-k(?:3|2\.(?:5|6|7)))(?:[-.].*)?$",
    re.IGNORECASE,
)


def is_responses_wire(wire_api: str | None) -> bool:
    return (wire_api or "").strip().lower() in {"responses", "response", "openai-responses"}


def responses_url(base_url: str) -> str:
    return (base_url or "").rstrip("/") + "/responses"


def responses_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def openai_tools_to_responses(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
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
        tool: dict[str, Any] = {
            "type": "function",
            "name": name,
            "description": str(fn.get("description") or ""),
            "parameters": schema,
        }
        if fn.get("strict") is True:
            tool["strict"] = True
        out.append(tool)
    return out


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or json.dumps(content, ensure_ascii=False))
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


def _tool_arguments(raw: Any) -> str:
    if raw is None:
        return "{}"
    if isinstance(raw, str):
        return raw or "{}"
    if isinstance(raw, dict):
        return json.dumps(raw, ensure_ascii=False)
    return json.dumps(raw, ensure_ascii=False)


def openai_messages_to_responses(
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
            converted.append(
                {
                    "type": "function_call_output",
                    "call_id": str(raw.get("tool_call_id") or raw.get("id") or "tool"),
                    "output": _content_to_text(raw.get("content")) or "",
                }
            )
            continue
        if role == "assistant":
            text = _content_to_text(raw.get("content"))
            if text.strip():
                item: dict[str, Any] = {"role": "assistant", "content": text}
                reasoning = raw.get("reasoning_content")
                if isinstance(reasoning, str) and reasoning.strip():
                    item["reasoning_content"] = reasoning
                converted.append(item)
            for tc in raw.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                name = str(fn.get("name") or "").strip()
                call_id = str(tc.get("id") or name or "tool")
                converted.append(
                    {
                        "type": "function_call",
                        "id": call_id,
                        "call_id": call_id,
                        "name": name,
                        "arguments": _tool_arguments(fn.get("arguments")),
                    }
                )
            continue
        if role in ("user", "developer"):
            text = _content_to_text(raw.get("content"))
            if not text.strip():
                continue
            converted.append({"role": role, "content": text})
    if not converted:
        converted.append({"role": "user", "content": "(empty)"})
    instructions = "\n\n".join(system_parts) if system_parts else None
    return instructions, converted


def _apply_temperature(body: dict[str, Any], model: str | None, temperature: float | None) -> None:
    slug = (model or "").strip().split("/")[-1]
    if temperature is None or (slug and _OMIT_TEMP.search(slug)):
        body.pop("temperature", None)
        return
    body["temperature"] = temperature


def build_responses_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    instructions, converted = openai_messages_to_responses(messages)
    body: dict[str, Any] = {
        "model": model,
        "input": converted,
    }
    if instructions:
        body["instructions"] = instructions
    converted_tools = openai_tools_to_responses(tools)
    if converted_tools:
        body["tools"] = converted_tools
        body["tool_choice"] = "auto"
    if max_output_tokens is not None:
        body["max_output_tokens"] = max(1, int(max_output_tokens))
    _apply_temperature(body, model, temperature)
    return body


def _usage_from_responses(raw: dict[str, Any] | None) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    prompt = int(src.get("input_tokens") or src.get("prompt_tokens") or 0)
    completion = int(src.get("output_tokens") or src.get("completion_tokens") or 0)
    details = src.get("input_tokens_details") if isinstance(src.get("input_tokens_details"), dict) else {}
    cached = int(details.get("cached_tokens") or src.get("cached_tokens") or 0)
    usage: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": int(src.get("total_tokens") or (prompt + completion)),
    }
    if cached:
        usage["cached_tokens"] = cached
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return usage


def _text_from_content(content: Any) -> tuple[str, str]:
    if isinstance(content, str):
        return content, ""
    if not isinstance(content, list):
        return _content_to_text(content), ""
    texts: list[str] = []
    reasoning: list[str] = []
    for part in content:
        if isinstance(part, str) and part:
            texts.append(part)
            continue
        if not isinstance(part, dict):
            continue
        ptype = str(part.get("type") or "")
        text = str(part.get("text") or part.get("content") or "")
        if ptype in ("reasoning", "reasoning_text", "summary_text"):
            if text:
                reasoning.append(text)
            continue
        if text:
            texts.append(text)
    return "".join(texts), "".join(reasoning)


def _reasoning_from_item(item: dict[str, Any]) -> str:
    parts: list[str] = []
    summary = item.get("summary")
    if isinstance(summary, list):
        for block in summary:
            if isinstance(block, dict):
                text = str(block.get("text") or block.get("content") or "")
                if text:
                    parts.append(text)
            elif isinstance(block, str) and block:
                parts.append(block)
    text = str(item.get("text") or item.get("content") or "")
    if text and not isinstance(item.get("content"), (list, dict)):
        parts.append(text)
    elif isinstance(item.get("content"), list):
        _text, extra = _text_from_content(item.get("content"))
        if extra:
            parts.append(extra)
        elif _text:
            parts.append(_text)
    return "".join(parts)


def _finish_reason(payload: dict[str, Any], tool_calls: list[Any]) -> str | None:
    status = str(payload.get("status") or "")
    details = payload.get("incomplete_details") if isinstance(payload.get("incomplete_details"), dict) else {}
    reason = str(details.get("reason") or "")
    if reason == "max_output_tokens" or status == "incomplete":
        return "length"
    if tool_calls:
        return "tool_calls"
    mapped = _STATUS_FINISH.get(status)
    if mapped:
        return mapped
    if status in ("completed", ""):
        return "stop"
    return status or "stop"


def unwrap_responses_payload(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("output"), list) or data.get("object") == "response":
        return data
    nested = data.get("response")
    if isinstance(nested, dict) and (
        isinstance(nested.get("output"), list) or nested.get("object") == "response"
    ):
        return nested
    return None


def looks_like_responses_payload(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return False
    if unwrap_responses_payload(data) is not None:
        return True
    return str(data.get("type") or "").startswith("response.")


def responses_to_openai(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "choices": [
                {"index": 0, "finish_reason": None, "message": {"role": "assistant", "content": None}}
            ]
        }
    if isinstance(data.get("choices"), list):
        return data
    payload = unwrap_responses_payload(data) or data
    output = payload.get("output") if isinstance(payload.get("output"), list) else []
    texts: list[str] = []
    reasoning: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for i, item in enumerate(output):
        if not isinstance(item, dict):
            continue
        itype = str(item.get("type") or "")
        if itype in ("message", "output_text") or item.get("role") == "assistant":
            text, extra = _text_from_content(item.get("content") if "content" in item else item.get("text"))
            if itype == "output_text" and not text:
                text = str(item.get("text") or "")
            if extra:
                reasoning.append(extra)
            if text:
                texts.append(text)
            continue
        if itype == "function_call":
            call_id = str(item.get("call_id") or item.get("id") or f"call_{i}")
            tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": str(item.get("name") or ""),
                        "arguments": _tool_arguments(item.get("arguments")),
                    },
                }
            )
            continue
        if itype == "reasoning":
            thought = _reasoning_from_item(item)
            if thought:
                reasoning.append(thought)
    if not texts and isinstance(payload.get("output_text"), str) and payload["output_text"]:
        texts.append(payload["output_text"])
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(texts) or None,
    }
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": payload.get("id") or data.get("id"),
        "model": payload.get("model") or data.get("model"),
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": _finish_reason(payload, tool_calls),
                "message": message,
            }
        ],
        "usage": _usage_from_responses(
            payload.get("usage") if isinstance(payload.get("usage"), dict) else data.get("usage")
        ),
    }
