from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from filewatch.agent.loop import run_builtin_agent
from filewatch.agent.tools import build_default_registry
from filewatch.config import ConfigError, parse_config_dict
from filewatch.models import FileEvent
from filewatch.llm import LlmError


def _event(path: str = "/tmp/x.md") -> FileEvent:
    return FileEvent(
        id="evt_1",
        ts="2020-01-01T00:00:00Z",
        watch_id="inbox",
        type="modified",
        path=path,
        is_dir=False,
    )


def test_builtin_config_defaults() -> None:
    cfg = parse_config_dict(
        {
            "name": "t",
            "watch": {"path": "/tmp/w"},
            "rules": [
                {
                    "name": "r1",
                    "when": {"types": ["created"], "glob": "**/*.md"},
                    "then": [
                        {
                            "agent": {
                                "prompt": "rewrite docs",
                            }
                        }
                    ],
                }
            ],
        }
    )
    action = cfg.rules[0].then[0]
    assert action.runner == "builtin"  # type: ignore[union-attr]
    assert action.max_steps == 24  # type: ignore[union-attr]


def test_builtin_requires_prompt() -> None:
    try:
        parse_config_dict(
            {
                "name": "t",
                "watch": {"path": "/tmp/w"},
                "rules": [
                    {
                        "name": "r1",
                        "when": {"types": ["created"]},
                        "then": [{"agent": {"runner": "builtin", "prompt": "  "}}],
                    }
                ],
            }
        )
        assert False, "expected ConfigError"
    except ConfigError as exc:
        assert "prompt" in str(exc)


def test_command_still_requires_argv() -> None:
    try:
        parse_config_dict(
            {
                "name": "t",
                "watch": {"path": "/tmp/w"},
                "rules": [
                    {
                        "name": "r1",
                        "when": {"types": ["created"]},
                        "then": [{"agent": {"runner": "command", "prompt": "x"}}],
                    }
                ],
            }
        )
        assert False, "expected ConfigError"
    except ConfigError as exc:
        assert "command" in str(exc)


def test_agent_loop_mock_tools(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("old", encoding="utf-8")
    script: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "Write",
                        "arguments": json.dumps({"path": "a.md", "content": "new"}),
                    },
                }
            ],
        },
        {"role": "assistant", "content": "已重写 a.md"},
    ]
    calls = {"n": 0}

    def fake_chat(messages, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        return script[idx]

    result = run_builtin_agent(
        prompt="rewrite a.md",
        event=_event(str(tmp_path / "a.md")),
        workspace=tmp_path,
        job_id="job_loop",
        log_dir=tmp_path / "logs",
        timeout_seconds=30,
        max_steps=5,
        chat=fake_chat,
        registry=build_default_registry(),
    )
    assert result.status == "ok"
    assert result.steps == 2
    assert result.tool_calls == 1
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "new"
    assert (tmp_path / "logs" / "job_loop.jsonl").exists()
    lines = (tmp_path / "logs" / "job_loop.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "Write"
    assert entry["ok"] is True


def test_agent_loop_llm_not_configured(tmp_path: Path) -> None:
    def boom(*args, **kwargs):
        raise LlmError("llm_not_configured", "请先在设置页填写 LLM API Key")

    result = run_builtin_agent(
        prompt="do stuff",
        event=_event(),
        workspace=tmp_path,
        job_id="job_nokey",
        log_dir=tmp_path / "logs",
        chat=boom,
    )
    assert result.status == "error"
    assert result.error == "llm_not_configured"
    assert "API Key" in (result.message or "")


def test_agent_loop_max_steps(tmp_path: Path) -> None:
    def always_tool(messages, **kwargs):
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c",
                    "type": "function",
                    "function": {"name": "Glob", "arguments": '{"pattern":"**/*"}'},
                }
            ],
        }

    result = run_builtin_agent(
        prompt="loop forever",
        event=_event(),
        workspace=tmp_path,
        job_id="job_steps",
        log_dir=tmp_path / "logs",
        max_steps=2,
        chat=always_tool,
    )
    assert result.status == "error"
    assert result.error == "max_steps"
    assert result.steps == 2
