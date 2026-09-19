from __future__ import annotations

import json
from typing import Any

from filewatch.anthropic_compat import (
    ANTHROPIC_VERSION,
    anthropic_headers,
    anthropic_message_to_openai,
    anthropic_url,
    build_anthropic_body,
    is_anthropic_wire,
    openai_messages_to_anthropic,
    openai_tools_to_anthropic,
)
from filewatch.llm import chat_complete, chat_messages, list_llm_models, parse_llm_models
from filewatch.responses_compat import (
    build_responses_body,
    is_responses_wire,
    openai_messages_to_responses,
    openai_tools_to_responses,
    responses_headers,
    responses_to_openai,
    responses_url,
)
from filewatch.settings import LlmConfig, normalize_wire_api


READ_TOOL = {
    "type": "function",
    "function": {
        "name": "Read",
        "description": "read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
}


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def test_wire_aliases() -> None:
    assert is_anthropic_wire("anthropic")
    assert is_anthropic_wire("messages")
    assert is_anthropic_wire("claude")
    assert not is_anthropic_wire("chat")
    assert is_responses_wire("responses")
    assert is_responses_wire("response")
    assert is_responses_wire("openai-responses")
    assert not is_responses_wire("anthropic")
    assert normalize_wire_api("messages") == "anthropic"
    assert normalize_wire_api("openai-responses") == "responses"
    assert normalize_wire_api("bogus") == "chat"


def test_headers_and_urls() -> None:
    ant = anthropic_headers("sk-ant")
    assert ant["x-api-key"] == "sk-ant"
    assert ant["Authorization"] == "Bearer sk-ant"
    assert ant["anthropic-version"] == ANTHROPIC_VERSION
    assert anthropic_url("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"
    resp = responses_headers("sk-test")
    assert resp["Authorization"] == "Bearer sk-test"
    assert responses_url("https://api.openai.com/v1") == "https://api.openai.com/v1/responses"


def test_openai_tools_to_anthropic() -> None:
    assert openai_tools_to_anthropic([READ_TOOL]) == [
        {
            "name": "Read",
            "description": "read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ]


def test_openai_tools_to_responses() -> None:
    assert openai_tools_to_responses([READ_TOOL]) == [
        {
            "type": "function",
            "name": "Read",
            "description": "read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    ]


def test_anthropic_messages_split_system_and_merge_tool_results() -> None:
    system, msgs = openai_messages_to_anthropic(
        [
            {"role": "system", "content": "you are a helper"},
            {"role": "user", "content": "look at a.java"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "toolu_1",
                        "type": "function",
                        "function": {"name": "Read", "arguments": '{"path":"a.java"}'},
                    },
                    {
                        "id": "toolu_2",
                        "type": "function",
                        "function": {"name": "Grep", "arguments": '{"pattern":"sink"}'},
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "toolu_1", "content": '{"ok":true}'},
            {"role": "tool", "tool_call_id": "toolu_2", "content": '{"ok":true,"hits":1}'},
            {"role": "user", "content": "请继续"},
        ]
    )
    assert system == "you are a helper"
    assert msgs[0] == {"role": "user", "content": "look at a.java"}
    assistant = msgs[1]
    assert assistant["role"] == "assistant"
    assert assistant["content"][0]["type"] == "tool_use"
    assert assistant["content"][0]["id"] == "toolu_1"
    assert assistant["content"][0]["input"] == {"path": "a.java"}
    assert assistant["content"][1]["name"] == "Grep"
    follow = msgs[2]
    assert follow["role"] == "user"
    blocks = follow["content"]
    assert [b["type"] for b in blocks] == ["tool_result", "tool_result", "text"]
    assert blocks[0]["tool_use_id"] == "toolu_1"
    assert blocks[2]["text"] == "请继续"


def test_responses_messages_split_system_and_tool_results() -> None:
    instructions, items = openai_messages_to_responses(
        [
            {"role": "system", "content": "you are a helper"},
            {"role": "user", "content": "look at a.java"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "Read", "arguments": '{"path":"a.java"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":true}'},
            {"role": "user", "content": "请继续"},
        ]
    )
    assert instructions == "you are a helper"
    assert items[0] == {"role": "user", "content": "look at a.java"}
    assert items[1]["type"] == "function_call"
    assert items[1]["call_id"] == "call_1"
    assert items[1]["name"] == "Read"
    assert json.loads(items[1]["arguments"]) == {"path": "a.java"}
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": '{"ok":true}',
    }
    assert items[3] == {"role": "user", "content": "请继续"}


def test_build_bodies() -> None:
    anthropic = build_anthropic_body(
        model="claude-sonnet-4-5",
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        tools=[],
        temperature=0.2,
    )
    assert anthropic["system"] == "sys"
    assert anthropic["messages"] == [{"role": "user", "content": "hi"}]
    assert anthropic["max_tokens"] == 8192
    assert "tools" not in anthropic
    responses = build_responses_body(
        model="gpt-4.1",
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        tools=[READ_TOOL],
        temperature=0.2,
    )
    assert responses["instructions"] == "sys"
    assert responses["input"] == [{"role": "user", "content": "hi"}]
    assert responses["temperature"] == 0.2
    assert responses["tools"][0]["name"] == "Read"
    assert responses["tool_choice"] == "auto"
    gpt5 = build_responses_body(
        model="gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
    )
    assert "temperature" not in gpt5


def test_anthropic_message_to_openai_tools_and_usage() -> None:
    out = anthropic_message_to_openai(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [
                {"type": "thinking", "thinking": "plan"},
                {"type": "text", "text": "calling"},
                {"type": "tool_use", "id": "toolu_9", "name": "Read", "input": {"path": "a.java"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 11, "output_tokens": 7, "cache_read_input_tokens": 3},
        }
    )
    msg = out["choices"][0]["message"]
    assert msg["content"] == "calling"
    assert msg["reasoning_content"] == "plan"
    assert msg["tool_calls"][0]["id"] == "toolu_9"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"path": "a.java"}
    assert out["choices"][0]["finish_reason"] == "tool_calls"
    assert out["usage"]["prompt_tokens"] == 11
    assert out["usage"]["cached_tokens"] == 3


def test_responses_to_openai_tools_and_usage() -> None:
    out = responses_to_openai(
        {
            "id": "resp_1",
            "object": "response",
            "status": "completed",
            "model": "gpt-test",
            "output": [
                {"type": "reasoning", "summary": [{"type": "summary_text", "text": "plan"}]},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "calling"}],
                },
                {
                    "type": "function_call",
                    "id": "fc_9",
                    "call_id": "call_9",
                    "name": "Read",
                    "arguments": '{"path":"a.java"}',
                },
            ],
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "total_tokens": 18,
                "input_tokens_details": {"cached_tokens": 3},
            },
        }
    )
    msg = out["choices"][0]["message"]
    assert msg["content"] == "calling"
    assert msg["reasoning_content"] == "plan"
    assert msg["tool_calls"][0]["id"] == "call_9"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"path": "a.java"}
    assert out["choices"][0]["finish_reason"] == "tool_calls"
    assert out["usage"]["prompt_tokens"] == 11
    assert out["usage"]["cached_tokens"] == 3


def _patch_llm(monkeypatch, cfg: LlmConfig, reply: dict[str, Any]) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float | None = None) -> FakeResponse:
        seen["url"] = request.full_url
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return FakeResponse(reply)

    monkeypatch.setattr("filewatch.llm.load_llm_config", lambda: cfg)
    monkeypatch.setattr("filewatch.llm.urllib.request.urlopen", fake_urlopen)
    return seen


def test_chat_complete_still_uses_chat_completions(monkeypatch) -> None:
    seen = _patch_llm(
        monkeypatch,
        LlmConfig(base_url="https://api.openai.com/v1", api_key="sk", model="gpt-4o-mini", wire_api="chat"),
        {
            "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}],
        },
    )
    text = chat_complete("sys", "hi")
    assert text == '{"ok": true}'
    assert seen["url"].endswith("/chat/completions")
    assert seen["body"]["messages"][0]["role"] == "system"


def test_chat_messages_anthropic(monkeypatch) -> None:
    seen = _patch_llm(
        monkeypatch,
        LlmConfig(base_url="https://api.anthropic.com/v1", api_key="sk-ant", model="claude-test", wire_api="anthropic"),
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "calling"},
                {"type": "tool_use", "id": "toolu_9", "name": "Read", "input": {"path": "a.java"}},
            ],
            "stop_reason": "tool_use",
        },
    )
    message = chat_messages(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        tools=[READ_TOOL],
    )
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-ant"
    assert seen["headers"]["anthropic-version"] == ANTHROPIC_VERSION
    assert seen["body"]["system"] == "sys"
    assert seen["body"]["tools"][0]["name"] == "Read"
    assert message["content"] == "calling"
    assert message["tool_calls"][0]["id"] == "toolu_9"


def test_chat_messages_responses(monkeypatch) -> None:
    seen = _patch_llm(
        monkeypatch,
        LlmConfig(base_url="https://api.openai.com/v1", api_key="sk", model="gpt-4.1", wire_api="responses"),
        {
            "id": "resp_1",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done"}],
                }
            ],
        },
    )
    message = chat_messages(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        tools=[READ_TOOL],
    )
    assert seen["url"] == "https://api.openai.com/v1/responses"
    assert seen["body"]["instructions"] == "sys"
    assert seen["body"]["input"] == [{"role": "user", "content": "hi"}]
    assert seen["body"]["tools"][0]["type"] == "function"
    assert message["content"] == "done"


def test_parse_llm_models_openai_and_anthropic() -> None:
    openai = parse_llm_models(
        {"object": "list", "data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4.1", "object": "model"}]}
    )
    assert openai == [{"id": "gpt-4.1", "name": "gpt-4.1"}, {"id": "gpt-4o-mini", "name": "gpt-4o-mini"}]
    assert parse_llm_models({"models": ["glm-5.3", "deepseek-chat", "Qwen3-max"]}) == [
        {"id": "deepseek-chat", "name": "deepseek-chat"},
        {"id": "glm-5.3", "name": "glm-5.3"},
        {"id": "Qwen3-max", "name": "Qwen3-max"},
    ]
    anthropic = parse_llm_models(
        {"data": [{"id": "claude-sonnet-4-5", "display_name": "Claude Sonnet 4.5"}, {"id": "claude-sonnet-4-5"}]}
    )
    assert anthropic == [{"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5"}]
    assert parse_llm_models({"models": ["deepseek-chat", "deepseek-reasoner"]}) == [
        {"id": "deepseek-chat", "name": "deepseek-chat"},
        {"id": "deepseek-reasoner", "name": "deepseek-reasoner"},
    ]
    assert parse_llm_models([{"name": "llama3:latest"}]) == [{"id": "llama3:latest", "name": "llama3:latest"}]
    assert parse_llm_models({"ok": True}) == []


def test_list_llm_models_uses_saved_and_overrides(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float | None = None) -> FakeResponse:
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["timeout"] = timeout
        return FakeResponse({"data": [{"id": "demo-a"}, {"id": "demo-b", "display_name": "Demo B"}]})

    monkeypatch.setattr(
        "filewatch.llm.load_llm_config",
        lambda: LlmConfig(base_url="https://api.openai.com/v1", api_key="sk-saved", model="gpt-4o-mini", wire_api="chat"),
    )
    monkeypatch.setattr("filewatch.llm.urllib.request.urlopen", fake_urlopen)
    result = list_llm_models()
    assert result["ok"] is True
    assert result["models"] == [{"id": "demo-a", "name": "demo-a"}, {"id": "demo-b", "name": "Demo B"}]
    assert seen["url"] == "https://api.openai.com/v1/models"
    assert seen["method"] == "GET"
    assert seen["headers"]["authorization"] == "Bearer sk-saved"

    result = list_llm_models(
        {
            "base_url": "https://api.anthropic.com/v1",
            "api_key": "sk-ant",
            "wire_api": "anthropic",
        }
    )
    assert result["ok"] is True
    assert seen["url"] == "https://api.anthropic.com/v1/models"
    assert seen["headers"]["x-api-key"] == "sk-ant"
    assert seen["headers"]["anthropic-version"] == ANTHROPIC_VERSION


def test_list_llm_models_requires_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "filewatch.llm.load_llm_config",
        lambda: LlmConfig(base_url="https://api.openai.com/v1", api_key="", model="gpt-4o-mini"),
    )
    result = list_llm_models()
    assert result["ok"] is False
    assert result["error"] == "llm_not_configured"
    result = list_llm_models({"base_url": "not-a-url", "api_key": "sk"})
    assert result["ok"] is False
    assert result["error"] == "bad_request"
    result = list_llm_models({"wire_api": "bogus", "api_key": "sk", "base_url": "https://api.openai.com/v1"})
    assert result["ok"] is False
    assert result["message"] == "wire_api 须为 chat、responses 或 anthropic"
