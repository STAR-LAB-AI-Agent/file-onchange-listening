from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

EVENT_TYPES = ("created", "modified", "deleted", "moved")
STREAMS = ("events", "jobs")
AGENT_RUNNERS = ("command", "cursor_sdk", "builtin")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class FileEvent:
    id: str
    ts: str
    watch_id: str
    type: str
    path: str
    old_path: str | None = None
    is_dir: bool = False
    line_changes: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "ts": self.ts,
            "watch_id": self.watch_id,
            "type": self.type,
            "path": self.path,
            "old_path": self.old_path,
            "is_dir": self.is_dir,
        }
        if self.line_changes is not None:
            payload["line_changes"] = self.line_changes
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileEvent:
        line_changes = data.get("line_changes")
        if line_changes is not None and not isinstance(line_changes, dict):
            line_changes = None
        return cls(
            id=str(data["id"]),
            ts=str(data["ts"]),
            watch_id=str(data["watch_id"]),
            type=str(data["type"]),
            path=str(data["path"]),
            old_path=data.get("old_path"),
            is_dir=bool(data.get("is_dir", False)),
            line_changes=line_changes,
        )


@dataclass(frozen=True)
class ActiveWindow:
    """Local-time window. Missing start/end/days means that dimension is unrestricted."""

    start_minute: int | None = None
    end_minute: int | None = None
    days: tuple[int, ...] = ()

    def contains(self, now: datetime) -> bool:
        start = 0 if self.start_minute is None else self.start_minute
        end = 1440 if self.end_minute is None else self.end_minute
        minute = now.hour * 60 + now.minute
        days = self.days or (1, 2, 3, 4, 5, 6, 7)
        iso = now.isoweekday()
        if start < end:
            return start <= minute < end and iso in days
        if minute >= start:
            return iso in days
        if minute < end:
            yesterday = 7 if iso == 1 else iso - 1
            return yesterday in days
        return False


@dataclass(frozen=True)
class When:
    types: tuple[str, ...] = EVENT_TYPES
    glob: tuple[str, ...] = ()
    regex: str | None = None
    is_dir: bool | None = None
    min_size_bytes: int | None = None
    cooldown_seconds: float = 0.0
    active: ActiveWindow | None = None


@dataclass(frozen=True)
class DingTalkTarget:
    webhook: str
    secret: str | None = None
    interval_seconds: float = 60.0


DEFAULT_DINGTALK_CHANNEL = "*"


@dataclass(frozen=True)
class DingTalkRef:
    """Rule-side DingTalk dest: settings channel id, or inline webhook (legacy)."""

    channel: str | None = None
    webhook: str | None = None
    secret: str | None = None
    interval_seconds: float = 60.0

    @property
    def enabled(self) -> bool:
        return bool((self.channel or "").strip()) or bool((self.webhook or "").strip())

    def inline_target(self) -> DingTalkTarget | None:
        webhook = (self.webhook or "").strip()
        if not webhook:
            return None
        secret = (self.secret or "").strip() or None
        return DingTalkTarget(webhook=webhook, secret=secret, interval_seconds=self.interval_seconds)


@dataclass(frozen=True)
class NotifyAction:
    title: str = "File watch"
    message: str = "{{type}}: {{path}}"
    webhook: str | None = None
    mailbox: bool = True
    dingtalk: DingTalkRef | None = None


@dataclass(frozen=True)
class AgentAction:
    runner: Literal["command", "cursor_sdk", "builtin"] = "builtin"
    prompt: str = "File {{type}}: {{path}}"
    command: tuple[str, ...] | None = None
    cwd: str | None = None
    timeout_seconds: float = 600.0
    model: str | None = None
    max_steps: int = 24


Action = NotifyAction | AgentAction


@dataclass(frozen=True)
class Rule:
    name: str
    when: When = field(default_factory=When)
    then: tuple[Action, ...] = ()
    enabled: bool = True
    exclude: bool = False


DEFAULT_IGNORE = (
    "**/.git/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/venv/**",
    "**/*.tmp",
)
DEFAULT_DEBOUNCE_MS = 400
DEFAULT_LINE_DIFF_QUIET_MS = 30_000
DEFAULT_LINE_DIFF_MAX_BYTES = 256 * 1024


@dataclass(frozen=True)
class WatchSettings:
    path: str
    recursive: bool = True
    debounce_ms: int = DEFAULT_DEBOUNCE_MS
    line_diff_quiet_ms: int = DEFAULT_LINE_DIFF_QUIET_MS
    line_diff_max_bytes: int = DEFAULT_LINE_DIFF_MAX_BYTES
    ignore: tuple[str, ...] = DEFAULT_IGNORE
    record_all: bool = True


@dataclass(frozen=True)
class Config:
    name: str
    watch: WatchSettings
    rules: tuple[Rule, ...] = ()
    max_parallel_jobs: int = 1
    source: str | None = None
