from __future__ import annotations

from pathlib import Path

from filewatch.config import parse_config_dict
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
