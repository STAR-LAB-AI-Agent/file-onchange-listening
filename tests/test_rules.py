from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from filewatch.config import ConfigError, config_to_dict, parse_config_dict
from filewatch.models import FileEvent
from filewatch.rules import RuleEngine


def _event(tmp_path: Path, name: str = "a.md", event_type: str = "created") -> FileEvent:
    path = tmp_path / name
    path.write_text("hello", encoding="utf-8")
    return FileEvent(
        id="evt_1",
        ts="2026-01-01T00:00:00Z",
        watch_id="demo",
        type=event_type,
        path=str(path),
        is_dir=False,
    )


def _engine(tmp_path: Path, when: dict) -> RuleEngine:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(tmp_path)},
            "rules": [{"name": "any", "when": when, "then": [{"notify": {}}]}],
        }
    )
    return RuleEngine(tmp_path, config.rules)


def test_glob_and_type_filters(tmp_path: Path) -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(tmp_path)},
            "rules": [
                {
                    "name": "md-created",
                    "when": {"types": ["created"], "glob": "**/*.md", "is_dir": False},
                    "then": [{"notify": {"message": "{{path}}"}}],
                }
            ],
        }
    )
    engine = RuleEngine(tmp_path, config.rules)
    assert [rule.name for rule in engine.matches(_event(tmp_path, "a.md"))] == ["md-created"]
    assert engine.matches(_event(tmp_path, "a.txt")) == []
    assert engine.matches(_event(tmp_path, "a.md", "modified")) == []


def test_cooldown(tmp_path: Path) -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(tmp_path)},
            "rules": [
                {
                    "name": "any",
                    "when": {"types": ["created"], "glob": "**/*", "cooldown_seconds": 60},
                    "then": [{"notify": {}}],
                }
            ],
        }
    )
    engine = RuleEngine(tmp_path, config.rules)
    event = _event(tmp_path)
    assert engine.matches(event)
    assert engine.matches(event) == []


def test_cooldown_expires(tmp_path: Path, monkeypatch) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr("filewatch.rules.time.monotonic", lambda: clock["now"])
    engine = _engine(tmp_path, {"types": ["created"], "glob": "**/*", "cooldown_seconds": 60})
    event = _event(tmp_path)
    assert engine.matches(event)
    clock["now"] = 150.0
    assert engine.matches(event) == []
    clock["now"] = 161.0
    assert [rule.name for rule in engine.matches(event)] == ["any"]


def test_regex_min_size_enabled_and_is_dir(tmp_path: Path) -> None:
    small = tmp_path / "notes-1.md"
    large = tmp_path / "notes-2.md"
    other = tmp_path / "skip.md"
    small.write_text("x", encoding="utf-8")
    large.write_text("hello world", encoding="utf-8")
    other.write_text("hello world", encoding="utf-8")
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(tmp_path)},
            "rules": [
                {
                    "name": "sized",
                    "when": {"types": ["created"], "regex": r"notes-\d+\.md$", "min_size_bytes": 8, "is_dir": False},
                    "then": [{"notify": {}}],
                },
                {
                    "name": "off",
                    "enabled": False,
                    "when": {"types": ["created"], "glob": "**/*"},
                    "then": [{"notify": {}}],
                },
                {
                    "name": "dirs",
                    "when": {"types": ["created"], "is_dir": True},
                    "then": [{"notify": {}}],
                },
            ],
        }
    )
    engine = RuleEngine(tmp_path, config.rules)
    file_event = FileEvent(
        id="e1",
        ts="2026-01-01T00:00:00Z",
        watch_id="demo",
        type="created",
        path=str(large),
        is_dir=False,
    )
    assert [rule.name for rule in engine.matches(file_event)] == ["sized"]
    small_event = FileEvent(**{**file_event.to_dict(), "path": str(small)})
    assert engine.matches(small_event) == []
    skip_event = FileEvent(**{**file_event.to_dict(), "path": str(other)})
    assert engine.matches(skip_event) == []
    dir_event = FileEvent(
        id="e2",
        ts="2026-01-01T00:00:00Z",
        watch_id="demo",
        type="created",
        path=str(tmp_path / "folder"),
        is_dir=True,
    )
    assert [rule.name for rule in engine.matches(dir_event)] == ["dirs"]
    missing = FileEvent(**{**file_event.to_dict(), "path": str(tmp_path / "gone.md"), "type": "deleted"})
    sized_only = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(tmp_path)},
            "rules": [
                {
                    "name": "sized",
                    "when": {"types": ["deleted"], "glob": "**/*", "min_size_bytes": 1},
                    "then": [{"notify": {}}],
                }
            ],
        }
    )
    assert RuleEngine(tmp_path, sized_only.rules).matches(missing) == []


def test_multiple_rules_can_hit_one_event(tmp_path: Path) -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(tmp_path)},
            "rules": [
                {"name": "any", "when": {"types": ["created"], "glob": "**/*"}, "then": [{"notify": {}}]},
                {"name": "md", "when": {"types": ["created"], "glob": "**/*.md"}, "then": [{"notify": {}}]},
            ],
        }
    )
    engine = RuleEngine(tmp_path, config.rules)
    assert [rule.name for rule in engine.matches(_event(tmp_path, "a.md"))] == ["any", "md"]


def test_duplicate_name_empty_then_and_bad_filters() -> None:
    with pytest.raises(ConfigError, match="不能重复"):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [
                    {"name": "a", "when": {"types": ["created"]}, "then": [{"notify": {}}]},
                    {"name": "a", "when": {"types": ["deleted"]}, "then": [{"notify": {}}]},
                ],
            }
        )
    with pytest.raises(ConfigError, match="then"):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [{"name": "a", "when": {"types": ["created"]}, "then": []}],
            }
        )
    with pytest.raises(ConfigError, match="regex"):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [{"name": "a", "when": {"types": ["created"], "regex": "["}, "then": [{"notify": {}}]}],
            }
        )
    with pytest.raises(ConfigError, match="空字符串"):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [{"name": "a", "when": {"types": ["created"], "glob": [""]}, "then": [{"notify": {}}]}],
            }
        )
    with pytest.raises(ConfigError, match="notify 或 agent"):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [{"name": "a", "when": {"types": ["created"]}, "then": [{"notify": {}, "agent": {}}]}],
            }
        )


def test_replace_rules_drops_removed_cooldown(tmp_path: Path) -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(tmp_path)},
            "rules": [
                {
                    "name": "any",
                    "when": {"types": ["created"], "glob": "**/*", "cooldown_seconds": 60},
                    "then": [{"notify": {}}],
                }
            ],
        }
    )
    engine = RuleEngine(tmp_path, config.rules)
    event = _event(tmp_path)
    assert engine.matches(event)
    replacement = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(tmp_path)},
            "rules": [
                {
                    "name": "other",
                    "when": {"types": ["created"], "glob": "**/*"},
                    "then": [{"notify": {}}],
                }
            ],
        }
    )
    engine.replace_rules(replacement.rules)
    assert [rule.name for rule in engine.matches(event)] == ["other"]


def test_active_omitted_always_matches(tmp_path: Path) -> None:
    engine = _engine(tmp_path, {"types": ["created"], "glob": "**/*"})
    event = _event(tmp_path)
    assert engine.matches(event, now=datetime(2026, 9, 14, 3, 0))
    assert engine.matches(event, now=datetime(2026, 9, 19, 23, 59))


def test_active_hours_and_weekdays(tmp_path: Path) -> None:
    engine = _engine(
        tmp_path,
        {
            "types": ["created"],
            "glob": "**/*",
            "active": {"start": "09:00", "end": "18:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
        },
    )
    event = _event(tmp_path)
    monday_noon = datetime(2026, 9, 14, 12, 0)
    monday_evening = datetime(2026, 9, 14, 18, 0)
    saturday_noon = datetime(2026, 9, 19, 12, 0)
    assert [rule.name for rule in engine.matches(event, now=monday_noon)] == ["any"]
    assert engine.matches(event, now=monday_evening) == []
    assert engine.matches(event, now=saturday_noon) == []


def test_active_string_range_and_overnight(tmp_path: Path) -> None:
    engine = _engine(tmp_path, {"types": ["created"], "glob": "**/*", "active": "22:00-06:00"})
    event = _event(tmp_path)
    friday_night = datetime(2026, 9, 18, 23, 0)
    saturday_early = datetime(2026, 9, 19, 1, 0)
    saturday_morning = datetime(2026, 9, 19, 6, 0)
    saturday_noon = datetime(2026, 9, 19, 12, 0)
    assert engine.matches(event, now=friday_night)
    assert engine.matches(event, now=saturday_early)
    assert engine.matches(event, now=saturday_morning) == []
    assert engine.matches(event, now=saturday_noon) == []


def test_active_overnight_respects_start_day(tmp_path: Path) -> None:
    engine = _engine(
        tmp_path,
        {
            "types": ["created"],
            "glob": "**/*",
            "active": {"start": "22:00", "end": "06:00", "days": ["fri"]},
        },
    )
    event = _event(tmp_path)
    friday_night = datetime(2026, 9, 18, 23, 30)
    saturday_early = datetime(2026, 9, 19, 1, 0)
    thursday_night = datetime(2026, 9, 17, 23, 30)
    assert engine.matches(event, now=friday_night)
    assert engine.matches(event, now=saturday_early)
    assert engine.matches(event, now=thursday_night) == []


def test_active_days_only(tmp_path: Path) -> None:
    engine = _engine(tmp_path, {"types": ["created"], "glob": "**/*", "active": {"days": [6, 7]}})
    event = _event(tmp_path)
    assert engine.matches(event, now=datetime(2026, 9, 19, 3, 0))
    assert engine.matches(event, now=datetime(2026, 9, 14, 12, 0)) == []


def test_active_roundtrip_and_defaults() -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": "."},
            "rules": [
                {
                    "name": "workday",
                    "when": {
                        "types": ["created"],
                        "glob": "**/*",
                        "active": {"start": "9:00", "end": "18:00", "days": ["周一", "tue", 3, "4", "fri"]},
                    },
                    "then": [{"notify": {}}],
                },
                {
                    "name": "always",
                    "when": {"types": ["created"], "glob": "**/*", "active": "00:00-24:00"},
                    "then": [{"notify": {}}],
                },
            ],
        }
    )
    dumped = config_to_dict(config)
    assert dumped["rules"][0]["when"]["active"] == {
        "start": "09:00",
        "end": "18:00",
        "days": ["mon", "tue", "wed", "thu", "fri"],
    }
    assert dumped["rules"][1]["when"]["active"] is None
    again = parse_config_dict(dumped)
    assert again.rules[0].when.active is not None
    assert again.rules[1].when.active is None


@pytest.mark.parametrize(
    "active, match",
    [
        ({"start": "09:00", "end": "09:00"}, "不能相同"),
        ({"days": ["noday"]}, "未知星期"),
        ("nope", "时间段"),
        (False, "不能为 false"),
    ],
)
def test_active_invalid(active, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [{"name": "bad", "when": {"types": ["created"], "active": active}, "then": [{"notify": {}}]}],
            }
        )
