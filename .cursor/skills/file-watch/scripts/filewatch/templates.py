from __future__ import annotations

import json
import os
import re
from typing import Any

from filewatch.models import FileEvent


_VAR = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def event_vars(event: FileEvent, extra: dict[str, Any] | None = None) -> dict[str, str]:
    values = {
        "id": event.id,
        "ts": event.ts,
        "watch_id": event.watch_id,
        "type": event.type,
        "path": event.path,
        "old_path": event.old_path or "",
        "is_dir": "true" if event.is_dir else "false",
        "json": json.dumps(event.to_dict(), ensure_ascii=False),
        "filename": os.path.basename(event.path),
    }
    if extra:
        for key, value in extra.items():
            values[key] = "" if value is None else str(value)
    return values


def render(template: str, event: FileEvent, extra: dict[str, Any] | None = None) -> str:
    values = event_vars(event, extra)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"unknown template variable: {key}")
        return values[key]

    return _VAR.sub(repl, template)


def render_argv(argv: tuple[str, ...] | list[str], event: FileEvent, extra: dict[str, Any] | None = None) -> list[str]:
    return [render(part, event, extra) for part in argv]
