from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from filewatch.models import (
    DEFAULT_DINGTALK_CHANNEL,
    DEFAULT_IGNORE,
    EVENT_TYPES,
    WEEKDAYS,
    ActiveWindow,
    AgentAction,
    Config,
    DingTalkRef,
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
        active=_parse_active(data.get("active")),
    )


_DAY_ALIASES = {
    "mon": 1,
    "monday": 1,
    "1": 1,
    "一": 1,
    "周一": 1,
    "星期一": 1,
    "tue": 2,
    "tues": 2,
    "tuesday": 2,
    "2": 2,
    "二": 2,
    "周二": 2,
    "星期二": 2,
    "wed": 3,
    "wednesday": 3,
    "3": 3,
    "三": 3,
    "周三": 3,
    "星期三": 3,
    "thu": 4,
    "thur": 4,
    "thurs": 4,
    "thursday": 4,
    "4": 4,
    "四": 4,
    "周四": 4,
    "星期四": 4,
    "fri": 5,
    "friday": 5,
    "5": 5,
    "五": 5,
    "周五": 5,
    "星期五": 5,
    "sat": 6,
    "saturday": 6,
    "6": 6,
    "六": 6,
    "周六": 6,
    "星期六": 6,
    "sun": 7,
    "sunday": 7,
    "0": 7,
    "7": 7,
    "日": 7,
    "天": 7,
    "周日": 7,
    "周天": 7,
    "星期日": 7,
    "星期天": 7,
}
_TIME_RE = re.compile(r"^(\d{1,2}):([0-5]\d)(?::([0-5]\d))?$")


def _parse_hhmm(raw: Any, *, field: str, allow_end_of_day: bool = False) -> int | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise ConfigError(f"{field} 必须是 HH:MM 字符串")
    text = raw.strip()
    if allow_end_of_day and text in {"24:00", "24:00:00"}:
        return 1440
    match = _TIME_RE.fullmatch(text)
    if not match:
        raise ConfigError(f"{field} 必须是 HH:MM（0:00–23:59）")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23:
        raise ConfigError(f"{field} 必须是 HH:MM（0:00–23:59）")
    return hour * 60 + minute


def _format_hhmm(minute: int | None) -> str | None:
    if minute is None:
        return None
    if minute == 1440:
        return "24:00"
    hour, mins = divmod(minute, 60)
    return f"{hour:02d}:{mins:02d}"


def _parse_days(raw: Any) -> tuple[int, ...]:
    if raw is None or raw == "":
        return ()
    if isinstance(raw, str):
        items = [part for part in re.split(r"[,，\s]+", raw) if part]
    elif isinstance(raw, list):
        items = raw
    else:
        raise ConfigError("when.active.days 必须是星期列表")
    days: list[int] = []
    seen: set[int] = set()
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise ConfigError("when.active.days 的项必须是星期名或 1–7")
        key = str(item).strip().lower()
        iso = _DAY_ALIASES.get(key)
        if iso is None:
            raise ConfigError(f"when.active.days 含未知星期 {item!r}，应为 {list(WEEKDAYS)} 或 1–7")
        if iso not in seen:
            seen.add(iso)
            days.append(iso)
    if len(days) == 7:
        return ()
    return tuple(days)


def _parse_active_range(text: str) -> tuple[int | None, int | None]:
    stripped = text.strip()
    if "-" not in stripped:
        raise ConfigError("when.active 时间段必须是 start-end，例如 09:00-18:00")
    start_raw, end_raw = stripped.split("-", 1)
    start = _parse_hhmm(start_raw.strip(), field="when.active.start")
    end = _parse_hhmm(end_raw.strip(), field="when.active.end", allow_end_of_day=True)
    return start, end


def _build_active(start: int | None, end: int | None, days: tuple[int, ...] = ()) -> ActiveWindow | None:
    if start is not None and end is not None and start == end:
        raise ConfigError("when.active.start 与 end 不能相同；全天请省略时间")
    if (start in {None, 0}) and (end in {None, 1440}) and not days:
        return None
    return ActiveWindow(start_minute=start, end_minute=end, days=days)


def _parse_active(raw: Any) -> ActiveWindow | None:
    if raw is None or raw is True or raw == "":
        return None
    if raw is False:
        raise ConfigError("when.active 不能为 false；停用规则请设 enabled: false")
    if isinstance(raw, str):
        start, end = _parse_active_range(raw)
        return _build_active(start, end)
    if not isinstance(raw, dict):
        raise ConfigError("when.active 必须是映射、时间段字符串，或省略")
    start = _parse_hhmm(raw.get("start"), field="when.active.start")
    end = _parse_hhmm(raw.get("end"), field="when.active.end", allow_end_of_day=True)
    return _build_active(start, end, _parse_days(raw.get("days")))


def dump_active(window: ActiveWindow | None) -> dict[str, Any] | None:
    if window is None:
        return None
    return {
        "start": _format_hhmm(window.start_minute),
        "end": _format_hhmm(window.end_minute),
        "days": [WEEKDAYS[day - 1] for day in window.days],
    }


def _parse_interval_seconds(raw: Any, *, default: float = 60.0) -> float:
    if raw is None or raw == "":
        return default
    try:
        interval_f = float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError("notify.dingtalk.interval_seconds 必须是数字") from exc
    if interval_f <= 0:
        raise ConfigError("notify.dingtalk.interval_seconds 必须大于 0")
    return interval_f


def _normalize_channel(raw: str) -> str:
    text = raw.strip()
    if text.lower() in {"true", "default", DEFAULT_DINGTALK_CHANNEL}:
        return DEFAULT_DINGTALK_CHANNEL
    return text


def _parse_dingtalk(raw: Any) -> DingTalkRef | None:
    if raw is None or raw is False:
        return None
    if raw is True:
        return DingTalkRef(channel=DEFAULT_DINGTALK_CHANNEL)
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text.lower() in {"false", "none", "null"}:
            return None
        return DingTalkRef(channel=_normalize_channel(text))
    if not isinstance(raw, dict):
        raise ConfigError("notify.dingtalk 必须是布尔值、渠道 id 或映射")
    channel_raw = raw.get("channel")
    if channel_raw is not None and not isinstance(channel_raw, str) and not isinstance(channel_raw, bool):
        raise ConfigError("notify.dingtalk.channel 必须是字符串")
    if channel_raw is True:
        channel = DEFAULT_DINGTALK_CHANNEL
    elif isinstance(channel_raw, str):
        channel = _normalize_channel(channel_raw) or None
    else:
        channel = None
    webhook_raw = raw.get("webhook")
    if webhook_raw is not None and not isinstance(webhook_raw, str):
        raise ConfigError("notify.dingtalk.webhook 必须是字符串")
    webhook = (webhook_raw or "").strip()
    secret_raw = raw.get("secret", raw.get("sec"))
    if secret_raw is not None and not isinstance(secret_raw, str):
        raise ConfigError("notify.dingtalk.secret 必须是字符串")
    secret = (secret_raw or "").strip() or None
    interval_f = _parse_interval_seconds(raw.get("interval_seconds", 60 if webhook else None))
    if webhook:
        if not webhook.startswith(("http://", "https://")):
            raise ConfigError("notify.dingtalk.webhook 必须是 http(s) 地址")
        return DingTalkRef(webhook=webhook, secret=secret, interval_seconds=interval_f)
    if secret and not channel:
        raise ConfigError("填写钉钉 SEC 时必须同时提供 notify.dingtalk.webhook 或 channel")
    if channel:
        return DingTalkRef(channel=channel)
    return None


def dump_dingtalk(ref: DingTalkRef | None) -> Any:
    if ref is None or not ref.enabled:
        return None
    if (ref.webhook or "").strip():
        return {
            "webhook": ref.webhook,
            "secret": ref.secret,
            "interval_seconds": ref.interval_seconds,
        }
    channel = (ref.channel or "").strip()
    if channel in {"", DEFAULT_DINGTALK_CHANNEL}:
        return True
    return {"channel": channel}


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
            dingtalk=_parse_dingtalk(payload.get("dingtalk")),
        )
    if kind == "agent":
        command = payload.get("command")
        argv = None
        if command is not None:
            if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
                raise ConfigError("agent.command 必须是字符串列表")
            argv = tuple(command)
        runner_raw = payload.get("runner")
        if runner_raw is None or runner_raw == "":
            runner = "command" if argv else "builtin"
        else:
            runner = str(runner_raw)
        if runner not in {"command", "cursor_sdk", "builtin"}:
            raise ConfigError("agent.runner 必须是 command、cursor_sdk 或 builtin")
        if runner == "command" and not argv:
            raise ConfigError("runner 为 command 时必须提供 agent.command")
        prompt = str(payload.get("prompt", "")).strip()
        if runner == "builtin" and not prompt:
            raise ConfigError("runner 为 builtin 时必须提供非空 agent.prompt（任务要求）")
        if not prompt:
            prompt = "File {{type}}: {{path}}"
        timeout = payload.get("timeout_seconds", 600)
        max_steps = payload.get("max_steps", 24)
        try:
            max_steps_i = int(max_steps)
        except (TypeError, ValueError) as exc:
            raise ConfigError("agent.max_steps 必须是整数") from exc
        if max_steps_i < 1:
            raise ConfigError("agent.max_steps 必须 >= 1")
        return AgentAction(
            runner=runner,  # type: ignore[arg-type]
            prompt=prompt,
            command=argv,
            cwd=payload.get("cwd"),
            timeout_seconds=float(timeout),
            model=payload.get("model"),
            max_steps=max_steps_i,
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
    debounce_ms = int(watch_raw.get("debounce_ms", 400))
    line_diff_quiet_ms = int(watch_raw.get("line_diff_quiet_ms", 2000))
    if debounce_ms < 0:
        raise ConfigError("watch.debounce_ms 必须 >= 0")
    if line_diff_quiet_ms < 0:
        raise ConfigError("watch.line_diff_quiet_ms 必须 >= 0")
    settings = WatchSettings(
        path=path,
        recursive=bool(watch_raw.get("recursive", True)),
        debounce_ms=debounce_ms,
        line_diff_quiet_ms=line_diff_quiet_ms,
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
            line_diff_quiet_ms=config.watch.line_diff_quiet_ms,
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
                "active": dump_active(rule.when.active),
                "actions": actions,
            }
        )
    return {
        "name": config.name,
        "watch_path": config.watch.path,
        "recursive": config.watch.recursive,
        "debounce_ms": config.watch.debounce_ms,
        "line_diff_quiet_ms": config.watch.line_diff_quiet_ms,
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
                            "dingtalk": dump_dingtalk(action.dingtalk),
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
                            "max_steps": action.max_steps,
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
                    "active": dump_active(rule.when.active),
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
            "line_diff_quiet_ms": config.watch.line_diff_quiet_ms,
            "ignore": list(config.watch.ignore),
        },
        "rules": rules,
        "source": config.source,
    }
