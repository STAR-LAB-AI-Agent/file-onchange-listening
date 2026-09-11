from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePosixPath


def state_root() -> Path:
    override = os.environ.get("FILEWATCH_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return (base / "filewatch").resolve()
    return (Path.home() / ".local" / "share" / "filewatch").resolve()


def watchers_root() -> Path:
    return state_root() / "watchers"


def watcher_dir(watch_id: str) -> Path:
    return watchers_root() / watch_id


def sanitize_id(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    if not slug:
        raise ValueError("watch id is empty after sanitizing")
    return slug[:64]


def to_posix(path: str | Path) -> str:
    return PurePosixPath(str(path).replace("\\", "/")).as_posix()


def relative_posix(root: Path, path: Path) -> str | None:
    try:
        return to_posix(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return None
