from __future__ import annotations

import json
from pathlib import Path

from filewatch.config import config_from_path, config_to_dict
from filewatch.service import allocate_watch_id, describe_watcher, save_rules, store_for, watcher_config


def _write_config(watch_id: str, folder: Path) -> None:
    store = store_for(watch_id)
    store.ensure()
    config = config_from_path(str(folder), name=watch_id)
    store.config_path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False), encoding="utf-8")


def test_allocate_watch_id_reuses_same_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    first = allocate_watch_id(inbox.resolve())
    _write_config(first, inbox)
    again = allocate_watch_id(inbox.resolve())
    assert first == "inbox"
    assert again == first


def test_allocate_watch_id_suffixes_same_folder_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    alpha = tmp_path / "alpha" / "inbox"
    beta = tmp_path / "beta" / "inbox"
    alpha.mkdir(parents=True)
    beta.mkdir(parents=True)
    first = allocate_watch_id(alpha.resolve())
    _write_config(first, alpha)
    second = allocate_watch_id(beta.resolve())
    assert first == "inbox"
    assert second.startswith("inbox-")
    assert second != first
    assert len(second) == len("inbox-") + 8


def test_describe_watcher_includes_title_and_last_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "reports"
    inbox.mkdir()
    _write_config("reports", inbox)
    store = store_for("reports")
    store.append("events", {"id": "evt_1", "type": "created", "path": str(inbox / "a.txt")})
    store.append("events", {"id": "evt_2", "type": "deleted", "path": str(inbox / "b.txt")})
    info = describe_watcher(store)
    assert info["title"] == "reports"
    assert info["event_count"] == 2
    assert info["last_event"]["id"] == "evt_2"
    assert info["path"] == str(inbox.resolve())


def test_save_rules_without_daemon(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_config("inbox", inbox)
    payload = save_rules(
        "inbox",
        [
            {
                "name": "md",
                "when": {"types": ["created"], "glob": ["**/*.md"], "is_dir": False},
                "then": [{"notify": {"title": "t", "message": "{{filename}}"}}],
            }
        ],
    )
    assert payload["ok"] is True
    assert payload["reloaded"] is False
    assert payload["rules"] == ["md"]
    config = watcher_config("inbox")
    assert config["config"]["rules"][0]["name"] == "md"
    assert config["rule_count"] == 1
