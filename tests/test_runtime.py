from __future__ import annotations

import sys
import time
from pathlib import Path

from filewatch.config import parse_config_dict
from filewatch.models import FileEvent
from filewatch.runtime import WatchRuntime, utc_now
from filewatch.store import WatchStore


def test_notify_and_agent_jobs(tmp_path: Path, monkeypatch) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    out = tmp_path / "agent-out.txt"
    helper = (
        Path(__file__).resolve().parents[1]
        / ".cursor"
        / "skills"
        / "file-watch"
        / "scripts"
        / "echo_agent.py"
    )
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(inbox), "debounce_ms": 1},
            "rules": [
                {
                    "name": "docs",
                    "when": {"types": ["created"], "glob": "**/*.md"},
                    "then": [
                        {"notify": {"title": "hit", "message": "{{filename}}"}},
                        {
                            "agent": {
                                "runner": "command",
                                "command": [sys.executable, str(helper)],
                                "prompt": "handle {{path}}",
                            }
                        },
                    ],
                }
            ],
        }
    )
    store = WatchStore("demo", root=tmp_path / "state")
    monkeypatch.setenv("FILEWATCH_AGENT_OUT", str(out))
    runtime = WatchRuntime(config, store)
    event = FileEvent(
        id="evt_1",
        ts=utc_now(),
        watch_id="demo",
        type="created",
        path=str(inbox / "note.md"),
        is_dir=False,
    )
    (inbox / "note.md").write_text("hi", encoding="utf-8")
    runtime._on_coalesced(event)
    seen: list[dict] = []
    cursor = 0
    deadline = time.time() + 5
    while time.time() < deadline and len(seen) < 2:
        items, cursor, _ = store.wait("jobs", cursor, timeout=0.5, limit=10)
        seen.extend(items)
    kinds = {job["kind"] for job in seen}
    assert kinds == {"notify", "agent"}
    assert all(job["status"] == "ok" for job in seen)
    deadline = time.time() + 5
    while time.time() < deadline and not out.exists():
        time.sleep(0.05)
    assert "handle" in out.read_text(encoding="utf-8")
    runtime.stop()


def test_watchdog_records_created_file(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    config = parse_config_dict(
        {
            "name": "live",
            "watch": {"path": str(inbox), "debounce_ms": 50},
            "rules": [
                {
                    "name": "any",
                    "when": {"types": ["created", "modified"], "glob": "**/*", "is_dir": False},
                    "then": [{"notify": {"message": "{{path}}"}}],
                }
            ],
        }
    )
    store = WatchStore("live", root=tmp_path / "state")
    runtime = WatchRuntime(config, store)
    runtime.start()
    try:
        (inbox / "hello.txt").write_text("hello", encoding="utf-8")
        items, _, timed_out = store.wait("events", 0, timeout=5, limit=20)
        assert not timed_out, "watchdog did not emit a created/modified event"
        paths = [item["path"] for item in items]
        assert any(path.endswith("hello.txt") for path in paths)
    finally:
        runtime.stop()
