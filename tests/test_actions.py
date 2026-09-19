from __future__ import annotations

import sys
from pathlib import Path
from urllib.request import Request

from filewatch.actions import ActionRunner
from filewatch.config import parse_config_dict
from filewatch.models import FileEvent
from filewatch.store import WatchStore


def _event(path: Path) -> FileEvent:
    return FileEvent(
        id="evt_1",
        ts="2026-01-01T00:00:00Z",
        watch_id="demo",
        type="created",
        path=str(path),
        is_dir=False,
    )


def _wait_jobs(store: WatchStore, *, want: int = 1, timeout: float = 3) -> list[dict]:
    items: list[dict] = []
    cursor = 0
    for _ in range(int(timeout / 0.2) + 1):
        chunk, cursor, _ = store.wait("jobs", cursor, timeout=0.2, limit=20)
        items.extend(chunk)
        if len(items) >= want:
            break
    return items


def test_webhook_ok_and_error(tmp_path: Path, monkeypatch) -> None:
    posted: list[str] = []

    class FakeResp:
        def read(self) -> bytes:
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    def fake_urlopen(request: Request, timeout: float = 15):
        posted.append(request.full_url)
        return FakeResp()

    monkeypatch.setattr("filewatch.actions.urlopen", fake_urlopen)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "a.md"
    target.write_text("x", encoding="utf-8")
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(inbox)},
            "rules": [
                {
                    "name": "hook",
                    "when": {"types": ["created"]},
                    "then": [{"notify": {"message": "{{filename}}", "webhook": "https://example.invalid/hook"}}],
                }
            ],
        }
    )
    store = WatchStore("demo", root=tmp_path / "state")
    store.ensure()
    runner = ActionRunner(store)
    try:
        runner.submit(_event(target), config.rules[0])
        items = _wait_jobs(store)
        assert items
        assert items[0]["webhook"] == "ok"
        assert posted
    finally:
        runner.close(wait=True)

    def boom(request: Request, timeout: float = 15):
        raise OSError("down")

    monkeypatch.setattr("filewatch.actions.urlopen", boom)
    runner = ActionRunner(store)
    try:
        runner.submit(_event(target), config.rules[0])
        items = _wait_jobs(store, want=2)
        assert any(job.get("webhook") == "error" and job.get("status") == "error" for job in items)
    finally:
        runner.close(wait=True)


def test_notify_dingtalk_missing_channel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "a.md"
    target.write_text("x", encoding="utf-8")
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(inbox)},
            "rules": [
                {
                    "name": "ding",
                    "when": {"types": ["created"]},
                    "then": [{"notify": {"message": "{{filename}}", "dingtalk": {"channel": "missing"}}}],
                }
            ],
        }
    )
    store = WatchStore("demo", root=tmp_path / "state")
    store.ensure()
    runner = ActionRunner(store)
    try:
        runner.submit(_event(target), config.rules[0])
        items = _wait_jobs(store)
        assert items
        assert items[0]["dingtalk"] == "error"
        assert items[0]["status"] == "error"
    finally:
        runner.close(wait=True)


def test_command_nonzero_exit(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "a.md"
    target.write_text("x", encoding="utf-8")
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(inbox)},
            "rules": [
                {
                    "name": "fail",
                    "when": {"types": ["created"]},
                    "then": [
                        {
                            "agent": {
                                "runner": "command",
                                "command": [sys.executable, "-c", "raise SystemExit(2)"],
                                "prompt": "x",
                            }
                        }
                    ],
                }
            ],
        }
    )
    store = WatchStore("demo", root=tmp_path / "state")
    store.ensure()
    runner = ActionRunner(store)
    try:
        runner.submit(_event(target), config.rules[0])
        items = _wait_jobs(store)
        assert items[0]["kind"] == "agent"
        assert items[0]["status"] == "error"
        assert "exited 2" in str(items[0].get("error") or "")
    finally:
        runner.close(wait=True)


def test_cursor_sdk_missing_module(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "cursor_sdk", None)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "a.md"
    target.write_text("x", encoding="utf-8")
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(inbox)},
            "rules": [
                {
                    "name": "sdk",
                    "when": {"types": ["created"]},
                    "then": [{"agent": {"runner": "cursor_sdk", "prompt": "do {{path}}"}}],
                }
            ],
        }
    )
    store = WatchStore("demo", root=tmp_path / "state")
    store.ensure()
    runner = ActionRunner(store)
    try:
        runner.submit(_event(target), config.rules[0])
        items = _wait_jobs(store)
        assert items[0]["status"] == "error"
        assert "cursor-sdk" in str(items[0].get("error") or "")
    finally:
        runner.close(wait=True)
