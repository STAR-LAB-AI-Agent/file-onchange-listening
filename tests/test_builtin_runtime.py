from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from filewatch.actions import ActionRunner
from filewatch.config import parse_config_dict
from filewatch.models import FileEvent
from filewatch.runtime import WatchRuntime
from filewatch.store import WatchStore
from filewatch.llm import LlmError


def test_suppress_path_blocks_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    watch = tmp_path / "w"
    watch.mkdir()
    cfg = parse_config_dict(
        {
            "name": "s",
            "watch": {"path": str(watch), "debounce_ms": 50},
            "rules": [
                {
                    "name": "all",
                    "when": {"types": ["created", "modified"], "glob": "**/*"},
                    "then": [{"notify": {"title": "t", "message": "{{path}}"}}],
                }
            ],
        }
    )
    store = WatchStore("s", tmp_path / "home" / "watchers" / "s")
    store.ensure()
    rt = WatchRuntime(cfg, store)
    target = watch / "x.md"
    target.write_text("a", encoding="utf-8")
    rt.suppress_path(str(target), ttl=1.0)

    from watchdog.events import FileModifiedEvent

    rt.handle_raw(FileModifiedEvent(str(target)))
    time.sleep(0.15)
    items, _, _ = store.wait("events", 0, timeout=0.2, limit=10)
    assert items == []

    time.sleep(1.1)
    rt.handle_raw(FileModifiedEvent(str(target)))
    time.sleep(0.2)
    items2, _, _ = store.wait("events", 0, timeout=0.5, limit=10)
    assert any(item.get("path") == str(target) or str(target) in str(item.get("path")) for item in items2)
    rt.stop()


def test_builtin_action_writes_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    watch = tmp_path / "ws"
    watch.mkdir()
    (watch / "a.md").write_text("old", encoding="utf-8")
    store = WatchStore("b", tmp_path / "home" / "watchers" / "b")
    store.ensure()

    script: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "content": "done",
        }
    ]
    idx = {"n": 0}

    def fake_chat(messages, **kwargs):
        i = idx["n"]
        idx["n"] += 1
        return script[i]

    monkeypatch.setattr("filewatch.agent.loop.chat_messages", fake_chat)

    cfg = parse_config_dict(
        {
            "name": "b",
            "watch": {"path": str(watch)},
            "rules": [
                {
                    "name": "task",
                    "when": {"types": ["modified"], "glob": "**/*.md"},
                    "then": [
                        {
                            "agent": {
                                "runner": "builtin",
                                "prompt": "noop {{path}}",
                                "max_steps": 3,
                            }
                        }
                    ],
                }
            ],
        }
    )
    runner = ActionRunner(store, max_workers=1, workspace=watch)
    event = FileEvent(
        id="e1",
        ts="2020-01-01T00:00:00Z",
        watch_id="b",
        type="modified",
        path=str(watch / "a.md"),
    )
    runner.submit(event, cfg.rules[0])
    items, _, _ = store.wait("jobs", 0, timeout=3, limit=5)
    runner.close(wait=True)
    assert items
    job = items[0]
    assert job["kind"] == "agent"
    assert job["runner"] == "builtin"
    assert job["status"] == "ok"
    assert job.get("steps") == 1


def _fake_chat(replies: list[dict[str, Any]]):
    idx = {"n": 0}

    def chat(messages, **kwargs):
        i = idx["n"]
        idx["n"] += 1
        return replies[i]

    return chat


def _dingtalk_hook() -> dict[str, object]:
    return {
        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
        "secret": "SECxxx",
    }


def test_builtin_pushes_last_reply_to_dingtalk(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append(
            {"webhook": webhook, "secret": secret, "payload": payload}
        ),
    )
    monkeypatch.setattr(
        "filewatch.agent.loop.chat_messages",
        _fake_chat(
            [
                {
                    "role": "assistant",
                    "content": "先读文件",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "Glob", "arguments": '{"pattern":"**/*"}'},
                        }
                    ],
                },
                {"role": "assistant", "content": "已重写 a.md\n完成。"},
            ]
        ),
    )
    watch = tmp_path / "ws"
    watch.mkdir()
    (watch / "a.md").write_text("old", encoding="utf-8")
    store = WatchStore("b", tmp_path / "home" / "watchers" / "b")
    store.ensure()
    cfg = parse_config_dict(
        {
            "name": "b",
            "watch": {"path": str(watch)},
            "rules": [
                {
                    "name": "task",
                    "when": {"types": ["modified"], "glob": "**/*.md"},
                    "then": [
                        {
                            "agent": {
                                "runner": "builtin",
                                "prompt": "noop {{path}}",
                                "max_steps": 3,
                                "dingtalk": _dingtalk_hook(),
                            }
                        }
                    ],
                }
            ],
        }
    )
    runner = ActionRunner(store, max_workers=1, workspace=watch)
    event = FileEvent(
        id="e1",
        ts="2020-01-01T00:00:00Z",
        watch_id="b",
        type="modified",
        path=str(watch / "a.md"),
    )
    try:
        runner.submit(event, cfg.rules[0])
        items, _, _ = store.wait("jobs", 0, timeout=3, limit=5)
        assert posted, "builtin 完成后应立刻推钉钉，不必等汇总窗口"
        text = posted[0]["payload"]["markdown"]["text"]
        assert "已重写 a.md" in text
        assert "先读文件" not in text
        assert "条变化" not in text
        assert items[0]["status"] == "ok"
        assert items[0]["dingtalk"] == "ok"
        assert items[0]["output"] == "已重写 a.md\n完成。"
    finally:
        runner.close(wait=True)
    assert len(posted) == 1


def test_builtin_inherits_notify_dingtalk(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append(payload),
    )
    monkeypatch.setattr(
        "filewatch.agent.loop.chat_messages",
        _fake_chat([{"role": "assistant", "content": "最后一轮回复"}]),
    )
    watch = tmp_path / "ws"
    watch.mkdir()
    (watch / "a.md").write_text("old", encoding="utf-8")
    store = WatchStore("b", tmp_path / "home" / "watchers" / "b")
    store.ensure()
    cfg = parse_config_dict(
        {
            "name": "b",
            "watch": {"path": str(watch)},
            "rules": [
                {
                    "name": "task",
                    "when": {"types": ["modified"], "glob": "**/*.md"},
                    "then": [
                        {
                            "notify": {
                                "title": "文件有变化",
                                "message": "{{filename}}",
                                "dingtalk": _dingtalk_hook(),
                            }
                        },
                        {
                            "agent": {
                                "runner": "builtin",
                                "prompt": "noop",
                                "max_steps": 3,
                            }
                        },
                    ],
                }
            ],
        }
    )
    runner = ActionRunner(store, max_workers=1, workspace=watch)
    event = FileEvent(
        id="e1",
        ts="2020-01-01T00:00:00Z",
        watch_id="b",
        type="modified",
        path=str(watch / "a.md"),
    )
    try:
        runner.submit(event, cfg.rules[0])
        items, _, _ = store.wait("jobs", 0, timeout=3, limit=10)
        agent_jobs = [item for item in items if item.get("kind") == "agent"]
        assert agent_jobs
        assert agent_jobs[0]["dingtalk"] == "ok"
        agent_posts = [item for item in posted if "最后一轮回复" in str(item.get("markdown", {}).get("text", ""))]
        assert agent_posts, "应在汇总刷新前就发出智能体最后一轮回复"
        assert all("条变化" not in str(item.get("markdown", {}).get("text", "")) for item in agent_posts)
    finally:
        runner.close(wait=True)


def test_builtin_skips_dingtalk_without_channel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append(payload),
    )
    monkeypatch.setattr(
        "filewatch.agent.loop.chat_messages",
        _fake_chat([{"role": "assistant", "content": "done"}]),
    )
    watch = tmp_path / "ws"
    watch.mkdir()
    (watch / "a.md").write_text("old", encoding="utf-8")
    store = WatchStore("b", tmp_path / "home" / "watchers" / "b")
    store.ensure()
    cfg = parse_config_dict(
        {
            "name": "b",
            "watch": {"path": str(watch)},
            "rules": [
                {
                    "name": "task",
                    "when": {"types": ["modified"]},
                    "then": [{"agent": {"runner": "builtin", "prompt": "noop"}}],
                }
            ],
        }
    )
    runner = ActionRunner(store, max_workers=1, workspace=watch)
    event = FileEvent(
        id="e1",
        ts="2020-01-01T00:00:00Z",
        watch_id="b",
        type="modified",
        path=str(watch / "a.md"),
    )
    try:
        runner.submit(event, cfg.rules[0])
        items, _, _ = store.wait("jobs", 0, timeout=3, limit=5)
        assert items[0]["status"] == "ok"
        assert "dingtalk" not in items[0]
        assert posted == []
    finally:
        runner.close(wait=True)


def test_builtin_skips_dingtalk_when_last_reply_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append(payload),
    )
    monkeypatch.setattr(
        "filewatch.agent.loop.chat_messages",
        _fake_chat([{"role": "assistant", "content": "   "}]),
    )
    watch = tmp_path / "ws"
    watch.mkdir()
    store = WatchStore("b", tmp_path / "home" / "watchers" / "b")
    store.ensure()
    cfg = parse_config_dict(
        {
            "name": "b",
            "watch": {"path": str(watch)},
            "rules": [
                {
                    "name": "task",
                    "when": {"types": ["modified"]},
                    "then": [
                        {
                            "agent": {
                                "runner": "builtin",
                                "prompt": "noop",
                                "dingtalk": _dingtalk_hook(),
                            }
                        }
                    ],
                }
            ],
        }
    )
    runner = ActionRunner(store, max_workers=1, workspace=watch)
    event = FileEvent(
        id="e1",
        ts="2020-01-01T00:00:00Z",
        watch_id="b",
        type="modified",
        path=str(watch / "a.md"),
    )
    try:
        runner.submit(event, cfg.rules[0])
        items, _, _ = store.wait("jobs", 0, timeout=3, limit=5)
        assert items[0]["status"] == "ok"
        assert items[0]["dingtalk"] == "skipped"
        assert posted == []
    finally:
        runner.close(wait=True)


def test_builtin_skips_dingtalk_on_agent_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append(payload),
    )

    def boom(*args, **kwargs):
        raise LlmError("llm_not_configured", "请先在设置页填写 LLM API Key")

    monkeypatch.setattr("filewatch.agent.loop.chat_messages", boom)
    watch = tmp_path / "ws"
    watch.mkdir()
    store = WatchStore("b", tmp_path / "home" / "watchers" / "b")
    store.ensure()
    cfg = parse_config_dict(
        {
            "name": "b",
            "watch": {"path": str(watch)},
            "rules": [
                {
                    "name": "task",
                    "when": {"types": ["modified"]},
                    "then": [
                        {
                            "agent": {
                                "runner": "builtin",
                                "prompt": "noop",
                                "dingtalk": _dingtalk_hook(),
                            }
                        }
                    ],
                }
            ],
        }
    )
    runner = ActionRunner(store, max_workers=1, workspace=watch)
    event = FileEvent(
        id="e1",
        ts="2020-01-01T00:00:00Z",
        watch_id="b",
        type="modified",
        path=str(watch / "a.md"),
    )
    try:
        runner.submit(event, cfg.rules[0])
        items, _, _ = store.wait("jobs", 0, timeout=3, limit=5)
        assert items[0]["status"] == "error"
        assert items[0]["dingtalk"] == "skipped"
        assert posted == []
    finally:
        runner.close(wait=True)


def test_builtin_dingtalk_failure_does_not_fail_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))

    def boom(webhook, secret, payload):
        raise RuntimeError("dingtalk down")

    monkeypatch.setattr("filewatch.dingtalk.send_dingtalk", boom)
    monkeypatch.setattr(
        "filewatch.agent.loop.chat_messages",
        _fake_chat([{"role": "assistant", "content": "已完成"}]),
    )
    watch = tmp_path / "ws"
    watch.mkdir()
    store = WatchStore("b", tmp_path / "home" / "watchers" / "b")
    store.ensure()
    cfg = parse_config_dict(
        {
            "name": "b",
            "watch": {"path": str(watch)},
            "rules": [
                {
                    "name": "task",
                    "when": {"types": ["modified"]},
                    "then": [
                        {
                            "agent": {
                                "runner": "builtin",
                                "prompt": "noop",
                                "dingtalk": _dingtalk_hook(),
                            }
                        }
                    ],
                }
            ],
        }
    )
    runner = ActionRunner(store, max_workers=1, workspace=watch)
    event = FileEvent(
        id="e1",
        ts="2020-01-01T00:00:00Z",
        watch_id="b",
        type="modified",
        path=str(watch / "a.md"),
    )
    try:
        runner.submit(event, cfg.rules[0])
        items, _, _ = store.wait("jobs", 0, timeout=3, limit=5)
        assert items[0]["status"] == "ok"
        assert items[0]["dingtalk"] == "error"
        assert "dingtalk down" in str(items[0].get("dingtalk_error") or "")
    finally:
        runner.close(wait=True)
