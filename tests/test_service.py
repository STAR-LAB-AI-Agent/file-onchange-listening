from __future__ import annotations

import json
from pathlib import Path

import pytest

from filewatch.config import ConfigError, config_from_path, config_to_dict, parse_config_dict
from filewatch.service import allocate_watch_id, apply_watch_timing, describe_watcher, rename_watcher, save_rules, store_for, watcher_config


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


def test_describe_watcher_uses_custom_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "reports"
    inbox.mkdir()
    store = store_for("reports")
    store.ensure()
    config = parse_config_dict({"name": "工作文档", "watch": {"path": str(inbox)}, "rules": []})
    store.config_path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False), encoding="utf-8")
    info = describe_watcher(store)
    assert info["watch_id"] == "reports"
    assert info["title"] == "工作文档"


def test_rename_watcher_updates_title_and_resets_to_folder(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_config("inbox", inbox)
    payload = rename_watcher("inbox", "  收件箱  ")
    assert payload["ok"] is True
    assert payload["watch_id"] == "inbox"
    assert payload["title"] == "收件箱"
    saved = json.loads(store_for("inbox").config_path.read_text(encoding="utf-8"))
    assert saved["name"] == "收件箱"
    reset = rename_watcher("inbox", "   ")
    assert reset["ok"] is True
    assert reset["title"] == "inbox"
    again = json.loads(store_for("inbox").config_path.read_text(encoding="utf-8"))
    assert again["name"] == "inbox"


def test_allocate_watch_id_non_ascii_folder(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    folder = tmp_path / "文档"
    folder.mkdir()
    watch_id = allocate_watch_id(folder.resolve())
    assert watch_id.startswith("watch-")
    assert len(watch_id) == len("watch-") + 12


def test_parse_watch_name_defaults_and_rejects(tmp_path: Path) -> None:
    inbox = tmp_path / "收件箱"
    inbox.mkdir()
    config = parse_config_dict({"watch": {"path": str(inbox)}, "rules": []})
    assert config.name == "收件箱"
    named = parse_config_dict({"name": "  工作 文档  ", "watch": {"path": str(inbox)}, "rules": []})
    assert named.name == "工作 文档"
    with pytest.raises(ConfigError, match="最长"):
        parse_config_dict({"name": "x" * 81, "watch": {"path": str(inbox)}, "rules": []})
    with pytest.raises(ConfigError, match="字符串"):
        parse_config_dict({"name": 12, "watch": {"path": str(inbox)}, "rules": []})


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


def test_apply_watch_timing_updates_stopped_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_config("inbox", inbox)
    before = watcher_config("inbox")["config"]["watch"]
    assert before["line_diff_quiet_ms"] == 30_000
    assert before["line_diff_max_bytes"] == 256 * 1024
    result = apply_watch_timing(120, 8000, 4096)
    assert result["ok"] is True
    assert result["watchers"][0]["watch_id"] == "inbox"
    assert result["watchers"][0]["reloaded"] is False
    after = watcher_config("inbox")["config"]["watch"]
    assert after["debounce_ms"] == 120
    assert after["line_diff_quiet_ms"] == 8000
    assert after["line_diff_max_bytes"] == 4096
    assert after["path"] == before["path"]
    assert after["record_all"] is True


def test_save_watch_options_record_all(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _write_config("inbox", inbox)
    from filewatch.service import save_watch_options

    payload = save_watch_options("inbox", record_all=False)
    assert payload["ok"] is True
    assert payload["record_all"] is False
    assert payload["applied"] is True
    assert payload["reloaded"] is False
    after = watcher_config("inbox")["config"]["watch"]
    assert after["record_all"] is False
    same = save_watch_options("inbox", record_all=False)
    assert same["ok"] is True
    assert same["applied"] is False
    missing = save_watch_options("missing", record_all=True)
    assert missing["ok"] is False
    assert missing["error"] == "not_found"
