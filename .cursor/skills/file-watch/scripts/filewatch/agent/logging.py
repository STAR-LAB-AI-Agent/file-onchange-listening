from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from filewatch.agent.types import ToolCallRecord


class ToolCallLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def log(self, record: ToolCallRecord) -> None:
        entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": record.name,
            "tool_call_id": record.id,
            "duration_ms": round(record.duration_ms, 2),
            "ok": record.result.ok,
            "input": record.arguments,
            "output": record.result.to_dict(),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
