from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.error:
            out["error"] = self.error
        if self.message:
            out["message"] = self.message
        if self.data is not None:
            if isinstance(self.data, dict):
                out.update(self.data)
            else:
                out["data"] = self.data
        return out

    def to_content(self) -> str:
        import json

        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class ToolContext:
    workspace: Path
    job_id: str
    watch_id: str
    suppress: Callable[[str, float], None] | None = None
    protected_roots: tuple[Path, ...] = ()
    shell_timeout: float = 60.0


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    parallel: bool
    execute: Callable[[dict[str, Any], ToolContext], ToolResult]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRecord:
    id: str
    name: str
    arguments: dict[str, Any]
    result: ToolResult
    duration_ms: float
