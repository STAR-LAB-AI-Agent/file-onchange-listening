from __future__ import annotations

import sys
import time
from pathlib import Path

from watchdog.events import DirModifiedEvent, FileCreatedEvent, FileDeletedEvent, FileMovedEvent

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
            "watch": {"path": str(inbox), "debounce_ms": 50, "line_diff_quiet_ms": 1},
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


def test_line_changes_after_quiet_window(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    config = parse_config_dict(
        {
            "name": "linediff",
            "watch": {
                "path": str(inbox),
                "debounce_ms": 1,
                "line_diff_quiet_ms": 50,
            },
            "rules": [],
        }
    )
    store = WatchStore("linediff", root=tmp_path / "state")
    runtime = WatchRuntime(config, store)
    note = inbox / "note.txt"
    try:
        note.write_text("line1\n", encoding="utf-8")
        runtime._on_coalesced(
            FileEvent(
                id="evt_create",
                ts=utc_now(),
                watch_id="linediff",
                type="created",
                path=str(note),
                is_dir=False,
            )
        )
        deadline = time.time() + 3
        created = None
        while time.time() < deadline:
            items, _ = store.read_since("events", 0)
            if items and items[0].get("line_changes", {}).get("kind") == "text":
                created = items[0]
                break
            time.sleep(0.05)
        assert created is not None
        assert created["line_changes"]["added"] == 1
        assert created["line_changes"]["removed"] == 0

        note.write_text("line1\nline2\n", encoding="utf-8")
        runtime._on_coalesced(
            FileEvent(
                id="evt_mod",
                ts=utc_now(),
                watch_id="linediff",
                type="modified",
                path=str(note),
                is_dir=False,
            )
        )
        modified = None
        deadline = time.time() + 3
        while time.time() < deadline:
            items, _ = store.read_since("events", 0)
            hit = next((item for item in items if item.get("id") == "evt_mod"), None)
            if hit and hit.get("line_changes", {}).get("kind") == "text":
                modified = hit
                break
            time.sleep(0.05)
        assert modified is not None
        assert modified["line_changes"]["added"] == 1
        assert any(row.get("text") == "line2" for row in modified["line_changes"]["changes"])
    finally:
        runtime.stop()


def _live_config(inbox: Path, **watch: object) -> dict:
    settings = {"path": str(inbox), "debounce_ms": 0, "line_diff_quiet_ms": 0, **watch}
    return {
        "name": "live",
        "watch": settings,
        "rules": [
            {
                "name": "any",
                "when": {"types": ["created", "modified", "deleted", "moved"], "glob": "**/*"},
                "then": [{"notify": {"message": "{{type}} {{path}} {{old_path}}"}}],
            }
        ],
    }


def test_handle_raw_deleted_moved_and_ignore(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    nested = inbox / "sub"
    nested.mkdir()
    store = WatchStore("live", root=tmp_path / "state")
    runtime = WatchRuntime(parse_config_dict(_live_config(inbox)), store)
    try:
        gone = inbox / "gone.txt"
        gone.write_text("x", encoding="utf-8")
        runtime.handle_raw(FileDeletedEvent(str(gone)))
        src = inbox / "old.txt"
        dest = inbox / "new.txt"
        src.write_text("x", encoding="utf-8")
        dest.write_text("x", encoding="utf-8")
        runtime.handle_raw(FileMovedEvent(str(src), str(dest)))
        runtime.handle_raw(FileCreatedEvent(str(inbox / "skip.tmp")))
        runtime.handle_raw(DirModifiedEvent(str(inbox)))
        runtime.handle_raw(FileCreatedEvent(str(store.dir / "noise.txt")))

        items, _, _ = store.wait("events", 0, timeout=1, limit=20)
        types = {item["type"] for item in items}
        assert "deleted" in types
        moved = [item for item in items if item["type"] == "moved"]
        assert moved
        assert moved[0]["path"].endswith("new.txt")
        assert str(moved[0].get("old_path") or "").endswith("old.txt")
        assert not any(str(item.get("path", "")).endswith(".tmp") for item in items)
        assert not any("noise.txt" in str(item.get("path", "")) for item in items)
        jobs, _, _ = store.wait("jobs", 0, timeout=2, limit=20)
        assert any(job.get("rule") == "any" for job in jobs)
    finally:
        runtime.stop()


def test_watchdog_non_recursive_skips_nested(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    nested = inbox / "nested"
    nested.mkdir(parents=True)
    store = WatchStore("live", root=tmp_path / "state")
    runtime = WatchRuntime(parse_config_dict(_live_config(inbox, recursive=False)), store)
    runtime.start()
    try:
        (nested / "deep.txt").write_text("nope", encoding="utf-8")
        time.sleep(0.4)
        (inbox / "root.txt").write_text("yes", encoding="utf-8")
        items, _, timed_out = store.wait("events", 0, timeout=5, limit=50)
        assert not timed_out
        paths = [item["path"] for item in items]
        assert any(path.endswith("root.txt") for path in paths)
        assert not any(path.endswith("deep.txt") for path in paths)
    finally:
        runtime.stop()
