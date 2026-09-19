from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filewatch.config import config_to_dict, parse_config_dict
from filewatch.frequent import (
    MIN_COUNT,
    WINDOW_SECONDS,
    collect_frequent_files,
    event_rel,
    exclude_rule_dict,
    unique_rule_name,
)
from filewatch.models import FileEvent
from filewatch.rules import RuleEngine
from filewatch.service import exclude_frequent_paths, list_frequent_files, store_for


NOW = datetime(2026, 9, 19, 7, 30, tzinfo=timezone.utc)


def _ts(seconds_ago: float) -> str:
    return (NOW - timedelta(seconds=seconds_ago)).isoformat()


def _event(path: str, seconds_ago: float, *, event_id: str, is_dir: bool = False) -> dict:
    return {
        "id": event_id,
        "type": "modified",
        "path": path,
        "ts": _ts(seconds_ago),
        "is_dir": is_dir,
    }


def test_collect_frequent_files_requires_min_count_in_window(tmp_path: Path) -> None:
    noisy = str(tmp_path / "app.log")
    quiet = str(tmp_path / "readme.md")
    records = [_event(noisy, index, event_id=f"n{index}") for index in range(MIN_COUNT)]
    records.extend(_event(quiet, index, event_id=f"q{index}") for index in range(MIN_COUNT - 1))
    found = collect_frequent_files(records, root=tmp_path, now=NOW)
    assert [item["rel"] for item in found] == ["app.log"]
    assert found[0]["count"] == MIN_COUNT
    assert found[0]["window_seconds"] == WINDOW_SECONDS
    assert found[0]["path"] == noisy


def test_collect_frequent_files_counts_superseded_pending_modified(tmp_path: Path) -> None:
    noisy = str(tmp_path / "app.log")
    records = []
    for index in range(MIN_COUNT):
        item = _event(noisy, index, event_id=f"p{index}")
        item["line_changes"] = {"kind": "pending"}
        records.append(item)
    found = collect_frequent_files(records, root=tmp_path, now=NOW)
    assert [item["rel"] for item in found] == ["app.log"]
    assert found[0]["count"] == MIN_COUNT


def test_collect_frequent_files_ignores_old_and_dirs(tmp_path: Path) -> None:
    log = str(tmp_path / "app.log")
    folder = str(tmp_path / "build")
    records = [_event(log, 5, event_id="fresh")]
    records.extend(_event(log, 120, event_id=f"old{i}") for i in range(10))
    records.extend(_event(folder, 1, event_id=f"d{i}", is_dir=True) for i in range(10))
    assert collect_frequent_files(records, root=tmp_path, now=NOW) == []


def test_collect_frequent_files_skips_already_excluded(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    log = str(inbox / "app.log")
    notes = str(inbox / "notes.md")
    config = parse_config_dict(
        {
            "name": "inbox",
            "watch": {"path": str(inbox)},
            "rules": [{"name": "skip-logs", "exclude": True, "when": {"glob": "**/*.log"}}],
        }
    )
    engine = RuleEngine(inbox, config.rules)
    records = [_event(log, i, event_id=f"l{i}") for i in range(MIN_COUNT)]
    records.extend(_event(notes, i, event_id=f"m{i}") for i in range(MIN_COUNT))
    found = collect_frequent_files(records, root=inbox, now=NOW, engine=engine, watch_id="inbox")
    assert [item["rel"] for item in found] == ["notes.md"]
    assert engine.exclude_hits(
        FileEvent(id="x", ts=NOW.isoformat(), watch_id="inbox", type="modified", path=log)
    )


def test_event_rel_uses_watch_root(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    nested = inbox / "logs" / "app.log"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")
    assert event_rel(inbox, str(nested)) == "logs/app.log"


def test_unique_rule_name_suffixes() -> None:
    assert unique_rule_name("skip-frequent", set()) == "skip-frequent"
    assert unique_rule_name("skip-frequent", {"skip-frequent"}) == "skip-frequent-2"
    assert unique_rule_name("skip-frequent", {"skip-frequent", "skip-frequent-2"}) == "skip-frequent-3"


def test_exclude_rule_dict_dedupes_globs() -> None:
    rule = exclude_rule_dict("skip-frequent", ["logs/app.log", "logs/app.log", "tmp/cache.dat"])
    assert rule["exclude"] is True
    assert rule["then"] == []
    assert rule["when"]["glob"] == ["logs/app.log", "tmp/cache.dat"]


def test_list_and_exclude_frequent_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    noisy = inbox / "app.log"
    other = inbox / "trace.log"
    store = store_for("inbox")
    store.ensure()
    config = parse_config_dict({"name": "inbox", "watch": {"path": str(inbox)}, "rules": []})
    store.config_path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False), encoding="utf-8")
    now = datetime.now(timezone.utc)
    for index in range(MIN_COUNT):
        ts = (now - timedelta(seconds=index)).isoformat()
        store.append(
            "events",
            {"id": f"a{index}", "type": "modified", "path": str(noisy), "ts": ts},
        )
        store.append(
            "events",
            {"id": f"b{index}", "type": "modified", "path": str(other), "ts": ts},
        )
    found = list_frequent_files(store)
    rels = {item["rel"] for item in found}
    assert rels == {"app.log", "trace.log"}
    payload = exclude_frequent_paths("inbox", [item["path"] for item in found])
    assert payload["ok"] is True
    assert payload["rule"] == "skip-frequent"
    assert payload["globs"] == ["app.log", "trace.log"]
    saved = store.read_json(store.config_path)
    assert saved is not None
    rule = saved["rules"][0]
    assert rule["exclude"] is True
    assert rule["when"]["glob"] == ["app.log", "trace.log"]
    assert list_frequent_files(store) == []
    again = exclude_frequent_paths("inbox", [str(noisy)])
    assert again["ok"] is True
    assert again["rule"] == "skip-frequent-2"
