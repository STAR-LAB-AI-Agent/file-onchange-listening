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
