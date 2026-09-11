from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from filewatch.models import (
    DEFAULT_IGNORE,
    AgentAction,
    Config,
    NotifyAction,
    Rule,
    WatchSettings,
    When,
)
from filewatch.paths import sanitize_id


class ConfigError(ValueError):
    pass


def _as_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        items = []
        for item in value:
            if not isinstance(item, str):
                raise ConfigError(f"{field} items must be strings")
            items.append(item)
        return tuple(items)
    raise ConfigError(f"{field} must be a string or list of strings")


def _parse_when(raw: Any) -> When:
    data = raw or {}
    if not isinstance(data, dict):
        raise ConfigError("rule.when must be a mapping")
    types = _as_tuple(data.get("types"), field="when.types") or None
    glob = _as_tuple(data.get("glob"), field="when.glob")
    regex = data.get("regex")
    if regex is not None and not isinstance(regex, str):
        raise ConfigError("when.regex must be a string")
    cooldown = data.get("cooldown_seconds", 0)
    min_size = data.get("min_size_bytes")
    is_dir = data.get("is_dir")
    if is_dir is not None and not isinstance(is_dir, bool):
        raise ConfigError("when.is_dir must be a boolean")
    if min_size is not None and not isinstance(min_size, int):
        raise ConfigError("when.min_size_bytes must be an integer")
    return When(
        types=tuple(types) if types else When().types,
        glob=glob,
        regex=regex,
        is_dir=is_dir,
        min_size_bytes=min_size,
        cooldown_seconds=float(cooldown),
    )


def _parse_action(raw: Any) -> NotifyAction | AgentAction:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ConfigError("each then item must be a mapping with one key: notify or agent")
    kind, payload = next(iter(raw.items()))
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ConfigError(f"{kind} action must be a mapping")
    if kind == "notify":
        webhook = payload.get("webhook")
        mailbox = payload.get("mailbox", True)
        if webhook is not None and not isinstance(webhook, str):
            raise ConfigError("notify.webhook must be a string")
        if not isinstance(mailbox, bool):
            raise ConfigError("notify.mailbox must be a boolean")
        return NotifyAction(
            title=str(payload.get("title", "File watch")),
            message=str(payload.get("message", "{{type}}: {{path}}")),
            webhook=webhook,
            mailbox=mailbox,
        )
    if kind == "agent":
        runner = str(payload.get("runner", "command"))
        if runner not in {"command", "cursor_sdk"}:
            raise ConfigError("agent.runner must be 'command' or 'cursor_sdk'")
        command = payload.get("command")
        argv = None
        if command is not None:
            if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
                raise ConfigError("agent.command must be a list of strings")
            argv = tuple(command)
        if runner == "command" and not argv:
            raise ConfigError("agent.command is required when runner is 'command'")
        timeout = payload.get("timeout_seconds", 600)
        return AgentAction(
            runner=runner,  # type: ignore[arg-type]
            prompt=str(payload.get("prompt", "File {{type}}: {{path}}")),
            command=argv,
            cwd=payload.get("cwd"),
            timeout_seconds=float(timeout),
            model=payload.get("model"),
        )
    raise ConfigError(f"unknown action: {kind}")


def _parse_rule(raw: Any, index: int) -> Rule:
    if not isinstance(raw, dict):
        raise ConfigError(f"rules[{index}] must be a mapping")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError(f"rules[{index}].name is required")
    then_raw = raw.get("then") or []
    if not isinstance(then_raw, list) or not then_raw:
        raise ConfigError(f"rules[{index}].then must be a non-empty list")
    return Rule(
        name=name,
        when=_parse_when(raw.get("when")),
        then=tuple(_parse_action(item) for item in then_raw),
        enabled=bool(raw.get("enabled", True)),
    )


def parse_config_dict(raw: dict[str, Any], *, source: str | None = None) -> Config:
    if "watch" not in raw or not isinstance(raw["watch"], dict):
        raise ConfigError("watch mapping is required")
    watch_raw = raw["watch"]
    path = watch_raw.get("path")
    if not path or not isinstance(path, str):
        raise ConfigError("watch.path is required")
    ignore = _as_tuple(watch_raw.get("ignore"), field="watch.ignore")
    settings = WatchSettings(
        path=path,
        recursive=bool(watch_raw.get("recursive", True)),
        debounce_ms=int(watch_raw.get("debounce_ms", 400)),
        ignore=ignore or DEFAULT_IGNORE,
    )
    name = raw.get("name")
    if name is None:
        name = Path(path).name or "watch"
    rules_raw = raw.get("rules") or []
    if not isinstance(rules_raw, list):
        raise ConfigError("rules must be a list")
    rules = tuple(_parse_rule(item, i) for i, item in enumerate(rules_raw))
    max_parallel = int(raw.get("max_parallel_jobs", 1))
    if max_parallel < 1:
        raise ConfigError("max_parallel_jobs must be >= 1")
    return Config(
        name=sanitize_id(str(name)),
        watch=settings,
        rules=rules,
        max_parallel_jobs=max_parallel,
        source=source,
    )


def load_config(path: str | Path) -> Config:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"config not found: {config_path}")
    text = config_path.read_text(encoding="utf-8")
    if config_path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    config = parse_config_dict(raw, source=str(config_path))
    watch_path = Path(config.watch.path)
    if not watch_path.is_absolute():
        watch_path = (config_path.parent / watch_path).resolve()
        config = Config(
            name=config.name,
            watch=WatchSettings(
                path=str(watch_path),
                recursive=config.watch.recursive,
                debounce_ms=config.watch.debounce_ms,
                ignore=config.watch.ignore,
            ),
            rules=config.rules,
            max_parallel_jobs=config.max_parallel_jobs,
            source=config.source,
        )
    else:
        config = Config(
            name=config.name,
            watch=WatchSettings(
                path=str(watch_path),
                recursive=config.watch.recursive,
                debounce_ms=config.watch.debounce_ms,
                ignore=config.watch.ignore,
            ),
            rules=config.rules,
            max_parallel_jobs=config.max_parallel_jobs,
            source=config.source,
        )
    return config


def config_from_path(path: str, *, name: str | None = None, recursive: bool = True) -> Config:
    resolved = Path(path).expanduser().resolve()
    return Config(
        name=sanitize_id(name or resolved.name or "watch"),
        watch=WatchSettings(path=str(resolved), recursive=recursive),
    )


def config_to_dict(config: Config) -> dict[str, Any]:
    rules = []
    for rule in config.rules:
        then = []
        for action in rule.then:
            if isinstance(action, NotifyAction):
                then.append(
                    {
                        "notify": {
                            "title": action.title,
                            "message": action.message,
                            "webhook": action.webhook,
                            "mailbox": action.mailbox,
                        }
                    }
                )
            else:
                then.append(
                    {
                        "agent": {
                            "runner": action.runner,
                            "prompt": action.prompt,
                            "command": list(action.command) if action.command else None,
                            "cwd": action.cwd,
                            "timeout_seconds": action.timeout_seconds,
                            "model": action.model,
                        }
                    }
                )
        rules.append(
            {
                "name": rule.name,
                "enabled": rule.enabled,
                "when": {
                    "types": list(rule.when.types),
                    "glob": list(rule.when.glob),
                    "regex": rule.when.regex,
                    "is_dir": rule.when.is_dir,
                    "min_size_bytes": rule.when.min_size_bytes,
                    "cooldown_seconds": rule.when.cooldown_seconds,
                },
                "then": then,
            }
        )
    return {
        "name": config.name,
        "max_parallel_jobs": config.max_parallel_jobs,
        "watch": {
            "path": config.watch.path,
            "recursive": config.watch.recursive,
            "debounce_ms": config.watch.debounce_ms,
            "ignore": list(config.watch.ignore),
        },
        "rules": rules,
        "source": config.source,
    }
