from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EVENT_TYPES = ("created", "modified", "deleted", "moved")
STREAMS = ("events", "jobs")
AGENT_RUNNERS = ("command", "cursor_sdk", "builtin")


@dataclass(frozen=True)
class FileEvent:
    id: str
    ts: str
    watch_id: str
    type: str
    path: str
    old_path: str | None = None
    is_dir: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "watch_id": self.watch_id,
            "type": self.type,
            "path": self.path,
            "old_path": self.old_path,
            "is_dir": self.is_dir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileEvent:
        return cls(
            id=str(data["id"]),
            ts=str(data["ts"]),
            watch_id=str(data["watch_id"]),
            type=str(data["type"]),
            path=str(data["path"]),
            old_path=data.get("old_path"),
            is_dir=bool(data.get("is_dir", False)),
        )


@dataclass(frozen=True)
class When:
    types: tuple[str, ...] = EVENT_TYPES
    glob: tuple[str, ...] = ()
    regex: str | None = None
    is_dir: bool | None = None
    min_size_bytes: int | None = None
    cooldown_seconds: float = 0.0


@dataclass(frozen=True)
class DingTalkTarget:
    webhook: str
    secret: str | None = None
    interval_seconds: float = 60.0


@dataclass(frozen=True)
class NotifyAction:
    title: str = "File watch"
    message: str = "{{type}}: {{path}}"
    webhook: str | None = None
    mailbox: bool = True
    dingtalk: DingTalkTarget | None = None


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


DEFAULT_IGNORE = (
    "**/.git/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/venv/**",
    "**/*.tmp",
)


@dataclass(frozen=True)
class WatchSettings:
    path: str
    recursive: bool = True
    debounce_ms: int = 400
    ignore: tuple[str, ...] = DEFAULT_IGNORE


@dataclass(frozen=True)
class Config:
    name: str
    watch: WatchSettings
    rules: tuple[Rule, ...] = ()
    max_parallel_jobs: int = 1
    source: str | None = None
