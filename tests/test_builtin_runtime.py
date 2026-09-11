from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from filewatch.actions import ActionRunner
from filewatch.config import parse_config_dict
from filewatch.models import FileEvent
from filewatch.runtime import WatchRuntime
from filewatch.store import WatchStore


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
