from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from filewatch.models import (
    DEFAULT_IGNORE,
    EVENT_TYPES,
    AgentAction,
    Config,
    FileEvent,
    NotifyAction,
    Rule,
    WatchSettings,
    When,
)
from filewatch.paths import sanitize_id
from filewatch.templates import render


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
                raise ConfigError(f"{field} 的项必须是字符串")
            items.append(item)
        return tuple(items)
    raise ConfigError(f"{field} 必须是字符串或字符串列表")


def _parse_when(raw: Any) -> When:
    data = raw or {}
    if not isinstance(data, dict):
        raise ConfigError("rule.when 必须是映射")
    types = _as_tuple(data.get("types"), field="when.types") or None
    glob = _as_tuple(data.get("glob"), field="when.glob")
    if any(not item for item in glob):
        raise ConfigError("when.glob 不能包含空字符串")
    regex = data.get("regex")
    if regex is not None and not isinstance(regex, str):
        raise ConfigError("when.regex 必须是字符串")
    if regex:
        try:
            re.compile(regex)
        except re.error as exc:
            raise ConfigError(f"when.regex 无效：{exc}") from exc
    cooldown = data.get("cooldown_seconds", 0)
    min_size = data.get("min_size_bytes")
    is_dir = data.get("is_dir")
    if is_dir is not None and not isinstance(is_dir, bool):
        raise ConfigError("when.is_dir 必须是布尔值")
    if min_size is not None and not isinstance(min_size, int):
        raise ConfigError("when.min_size_bytes 必须是整数")
    resolved_types = tuple(types) if types else When().types
    unknown = [item for item in resolved_types if item not in EVENT_TYPES]
    if unknown:
        raise ConfigError(f"when.types 含未知类型 {unknown}，应为 {list(EVENT_TYPES)}")
    return When(
        types=resolved_types,
        glob=glob,
        regex=regex,
        is_dir=is_dir,
        min_size_bytes=min_size,
        cooldown_seconds=float(cooldown),
    )


def _parse_action(raw: Any) -> NotifyAction | AgentAction:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise ConfigError("then 每一项必须是只含 notify 或 agent 之一的映射")
    kind, payload = next(iter(raw.items()))
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ConfigError(f"{kind} 动作必须是映射")
    if kind == "notify":
        webhook = payload.get("webhook")
        mailbox = payload.get("mailbox", True)
        if webhook is not None and not isinstance(webhook, str):
            raise ConfigError("notify.webhook 必须是字符串")
        if not isinstance(mailbox, bool):
            raise ConfigError("notify.mailbox 必须是布尔值")
        return NotifyAction(
            title=str(payload.get("title", "File watch")),
            message=str(payload.get("message", "{{type}}: {{path}}")),
            webhook=webhook,
            mailbox=mailbox,
        )
    if kind == "agent":
        runner = str(payload.get("runner", "command"))
        if runner not in {"command", "cursor_sdk"}:
            raise ConfigError("agent.runner 必须是 command 或 cursor_sdk")
        command = payload.get("command")
        argv = None
        if command is not None:
            if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
                raise ConfigError("agent.command 必须是字符串列表")
            argv = tuple(command)
        if runner == "command" and not argv:
            raise ConfigError("runner 为 command 时必须提供 agent.command")
        timeout = payload.get("timeout_seconds", 600)
        return AgentAction(
            runner=runner,  # type: ignore[arg-type]
            prompt=str(payload.get("prompt", "File {{type}}: {{path}}")),
            command=argv,
            cwd=payload.get("cwd"),
            timeout_seconds=float(timeout),
            model=payload.get("model"),
        )
    raise ConfigError(f"未知动作：{kind}")


def _parse_rule(raw: Any, index: int) -> Rule:
    if not isinstance(raw, dict):
        raise ConfigError(f"rules[{index}] 必须是映射")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError(f"rules[{index}].name 必填")
    then_raw = raw.get("then") or []
    if not isinstance(then_raw, list) or not then_raw:
        raise ConfigError(f"rules[{index}].then 必须是非空列表")
    return Rule(
        name=name,
        when=_parse_when(raw.get("when")),
        then=tuple(_parse_action(item) for item in then_raw),
        enabled=bool(raw.get("enabled", True)),
    )


def _must_render(text: str, event: FileEvent, extra: dict[str, Any], field: str) -> None:
    try:
        render(text, event, extra)
    except KeyError as exc:
        raise ConfigError(f"{field} 含未知模板变量：{exc}") from exc


def _lint_templates(config: Config) -> None:
    dummy = FileEvent(
        id="evt_0",
        ts="1970-01-01T00:00:00Z",
        watch_id=config.name,
        type="created",
        path="/tmp/file.txt",
        old_path="/tmp/old.txt",
        is_dir=False,
    )
    for rule in config.rules:
        extra = {"rule": rule.name, "title": "x"}
        for index, action in enumerate(rule.then):
            prefix = f"rules[{rule.name}].then[{index}]"
            if isinstance(action, NotifyAction):
                _must_render(action.title, dummy, extra, f"{prefix}.notify.title")
                _must_render(action.message, dummy, extra, f"{prefix}.notify.message")
                if action.webhook:
                    _must_render(action.webhook, dummy, extra, f"{prefix}.notify.webhook")
            else:
                _must_render(action.prompt, dummy, extra, f"{prefix}.agent.prompt")
                if action.cwd:
                    _must_render(action.cwd, dummy, extra, f"{prefix}.agent.cwd")
                if action.command:
                    for part_index, part in enumerate(action.command):
                        _must_render(part, dummy, extra, f"{prefix}.agent.command[{part_index}]")


def parse_config_dict(raw: dict[str, Any], *, source: str | None = None) -> Config:
    if "watch" not in raw or not isinstance(raw["watch"], dict):
        raise ConfigError("必须提供 watch 映射")
    watch_raw = raw["watch"]
    path = watch_raw.get("path")
    if not path or not isinstance(path, str):
        raise ConfigError("watch.path 必填")
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
        raise ConfigError("rules 必须是列表")
    rules = tuple(_parse_rule(item, i) for i, item in enumerate(rules_raw))
    names = [rule.name for rule in rules]
    if len(names) != len(set(names)):
        raise ConfigError("规则 name 不能重复")
    max_parallel = int(raw.get("max_parallel_jobs", 1))
    if max_parallel < 1:
        raise ConfigError("max_parallel_jobs 必须 >= 1")
    config = Config(
        name=sanitize_id(str(name)),
        watch=settings,
        rules=rules,
        max_parallel_jobs=max_parallel,
        source=source,
    )
    _lint_templates(config)
    return config


def _with_watch_path(config: Config, watch_path: Path) -> Config:
    return Config(
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


def load_config(path: str | Path) -> Config:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"找不到配置文件：{config_path}")
    text = config_path.read_text(encoding="utf-8")
    try:
        if config_path.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            raw = yaml.safe_load(text)
        else:
            raw = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"配置无法解析：{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置根节点必须是映射")
    config = parse_config_dict(raw, source=str(config_path))
    watch_path = Path(config.watch.path)
    if not watch_path.is_absolute():
        watch_path = (config_path.parent / watch_path).resolve()
    else:
        watch_path = watch_path.resolve()
    return _with_watch_path(config, watch_path)


def config_from_path(path: str, *, name: str | None = None, recursive: bool = True) -> Config:
    resolved = Path(path).expanduser().resolve()
    return Config(
        name=sanitize_id(name or resolved.name or "watch"),
        watch=WatchSettings(path=str(resolved), recursive=recursive),
    )


def summarize_config(config: Config) -> dict[str, Any]:
    rules = []
    for rule in config.rules:
        actions = []
        for action in rule.then:
            if isinstance(action, NotifyAction):
                actions.append("notify")
            else:
                actions.append("agent")
        rules.append(
            {
                "name": rule.name,
                "enabled": rule.enabled,
                "types": list(rule.when.types),
                "glob": list(rule.when.glob),
                "regex": rule.when.regex,
                "is_dir": rule.when.is_dir,
                "min_size_bytes": rule.when.min_size_bytes,
                "cooldown_seconds": rule.when.cooldown_seconds,
                "actions": actions,
            }
        )
    return {
        "name": config.name,
        "watch_path": config.watch.path,
        "recursive": config.watch.recursive,
        "debounce_ms": config.watch.debounce_ms,
        "ignore": list(config.watch.ignore),
        "max_parallel_jobs": config.max_parallel_jobs,
        "rules": rules,
        "rule_count": len(rules),
    }


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
