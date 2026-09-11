from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from filewatch.config import ConfigError, config_to_dict, parse_config_dict
from filewatch.models import FileEvent
from filewatch.runtime import ReloadError, WatchRuntime, utc_now
from filewatch.store import WatchStore

from test_cli import _run


def _config(inbox: Path, glob: str, name: str = "demo") -> dict:
    return {
        "name": name,
        "watch": {"path": str(inbox), "debounce_ms": 1},
        "rules": [
            {
                "name": "hit",
                "when": {"types": ["created"], "glob": glob, "is_dir": False},
                "then": [{"notify": {"title": "t", "message": "{{filename}}"}}],
            }
        ],
    }


def test_apply_reload_swaps_rules(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    store = WatchStore("demo", root=tmp_path / "state")
    runtime = WatchRuntime(parse_config_dict(_config(inbox, "**/*.txt")), store)
    try:
        md = parse_config_dict(_config(inbox, "**/*.md"))
        result = runtime.apply_reload(md)
        assert result["rules"][0]["glob"] == ["**/*.md"]
        event = FileEvent(
            id="evt_1",
            ts=utc_now(),
            watch_id="demo",
            type="created",
            path=str(inbox / "note.md"),
            is_dir=False,
        )
        (inbox / "note.md").write_text("x", encoding="utf-8")
        runtime._on_coalesced(event)
        items, _, timed_out = store.wait("jobs", 0, timeout=2, limit=10)
        assert not timed_out
        assert items[0]["rule"] == "hit"
    finally:
        runtime.debouncer.close()
        runtime.actions.close(wait=False)


def test_apply_reload_rejects_path_change(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    other = tmp_path / "other"
    inbox.mkdir()
    other.mkdir()
    store = WatchStore("demo", root=tmp_path / "state")
    runtime = WatchRuntime(parse_config_dict(_config(inbox, "**/*")), store)
    try:
        with pytest.raises(ReloadError) as caught:
            runtime.apply_reload(parse_config_dict(_config(other, "**/*")))
        assert caught.value.error == "needs_restart"
    finally:
        runtime.debouncer.close()
        runtime.actions.close(wait=False)


def test_validate_accepts_and_rejects(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    good = tmp_path / "good.yaml"
    good.write_text(
        f"name: demo\nwatch:\n  path: {inbox.as_posix()}\nrules:\n"
        "  - name: md\n    when:\n      types: [created]\n      glob: '**/*.md'\n"
        "    then:\n      - notify:\n          message: '{{path}}'\n",
        encoding="utf-8",
    )
    code, payload = _run(tmp_path / "home", ["validate", "--config", str(good)])
    assert code == 0
    assert payload["ok"] is True
    assert payload["rules"][0]["name"] == "md"

    bad = tmp_path / "bad.yaml"
    bad.write_text(
        f"name: demo\nwatch:\n  path: {inbox.as_posix()}\nrules:\n"
        "  - name: md\n    when:\n      types: [created]\n      glob: '**/*.md'\n"
        "    then:\n      - notify:\n          message: '{{nope}}'\n",
        encoding="utf-8",
    )
    code, payload = _run(tmp_path / "home", ["validate", "--config", str(bad)])
    assert code == 1
    assert payload["error"] == "bad_config"


def test_unknown_event_type_is_invalid() -> None:
    with pytest.raises(ConfigError, match="when.types"):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [
                    {
                        "name": "bad",
                        "when": {"types": ["create"]},
                        "then": [{"notify": {}}],
                    }
                ],
            }
        )


def test_cli_reload_hot_applies_rules(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("FILEWATCH_HOME", str(home))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    cfg = tmp_path / "watch.yaml"
    cfg.write_text(
        f"name: demo\nwatch:\n  path: {inbox.as_posix()}\n  debounce_ms: 1\nrules:\n"
        "  - name: txt\n    when:\n      types: [created]\n      glob: '**/*.txt'\n"
        "    then:\n      - notify:\n          message: '{{filename}}'\n",
        encoding="utf-8",
    )
    from filewatch.config import load_config

    config = load_config(cfg)
    store = WatchStore(config.name)
    runtime = WatchRuntime(config, store)
    store.ensure()
    store.write_pid(os.getpid())
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            runtime._poll_control()
            time.sleep(0.05)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    try:
        cfg.write_text(
            f"name: demo\nwatch:\n  path: {inbox.as_posix()}\n  debounce_ms: 1\nrules:\n"
            "  - name: md-only\n    when:\n      types: [created]\n      glob: '**/*.md'\n"
            "    then:\n      - notify:\n          message: '{{filename}}'\n",
            encoding="utf-8",
        )
        code, payload = _run(home, ["reload", "--config", str(cfg), "--id", "demo"])
        assert code == 0, payload
        assert payload["ok"] is True
        assert "md-only" in payload["rules"]
        event = FileEvent(
            id="evt_1",
            ts=utc_now(),
            watch_id="demo",
            type="created",
            path=str(inbox / "note.md"),
            is_dir=False,
        )
        (inbox / "note.md").write_text("x", encoding="utf-8")
        runtime._on_coalesced(event)
        items, _, timed_out = store.wait("jobs", 0, timeout=2, limit=10)
        assert not timed_out
        assert items[0]["rule"] == "md-only"
    finally:
        stop.set()
        thread.join(timeout=2)
        runtime.debouncer.close()
        runtime.actions.close(wait=False)


def test_handle_reload_writes_status(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    store = WatchStore("demo", root=tmp_path / "state")
    runtime = WatchRuntime(parse_config_dict(_config(inbox, "**/*.txt")), store)
    try:
        store.request_reload(config_to_dict(parse_config_dict(_config(inbox, "**/*.md"))), "g1")
        runtime._handle_reload()
        status = store.read_reload_status()
        assert status is not None
        assert status["ok"] is True
        assert status["generation"] == "g1"
        assert store.reload_requested() is False
    finally:
        runtime.debouncer.close()
        runtime.actions.close(wait=False)
