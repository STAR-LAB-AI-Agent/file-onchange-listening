from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filewatch.linediff import is_noop_text_modified
from filewatch.models import EVENT_TYPES, FileEvent
from filewatch.paths import relative_posix, sanitize_id, to_posix
from filewatch.rules import RuleEngine
from filewatch.store import parse_event_ts

WINDOW_SECONDS = 45
MIN_COUNT = 6
MAX_CANDIDATES = 30
TAIL_LIMIT = 400
TAIL_MAX_BYTES = 524288
RULE_NAME = "skip-frequent"


def unique_rule_name(base: str, taken: set[str]) -> str:
    slug = sanitize_id(base or "rule")[:48]
    if slug not in taken:
        return slug
    index = 2
    while f"{slug}-{index}" in taken:
        index += 1
    return f"{slug}-{index}"


def path_key(path: str) -> str:
    posix = to_posix(path)
    if sys.platform == "win32":
        return posix.casefold()
    return posix


def event_rel(root: Path | None, path_str: str) -> str:
    posix = to_posix(path_str).lstrip("./")
    if root is None:
        return posix
    try:
        rel = relative_posix(root, Path(path_str))
    except OSError:
        rel = None
    if rel:
        return rel
    root_posix = to_posix(root)
    left = root_posix.casefold() if sys.platform == "win32" else root_posix
    right = posix.casefold() if sys.platform == "win32" else posix
    prefix = f"{left}/"
    if right.startswith(prefix):
        return posix[len(root_posix) + 1 :]
    if right == left:
        return "."
    return posix


def countable_event_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Keep superseded pending modified: the event list hides them, but they are the flood.
    return [record for record in records if not is_noop_text_modified(record)]


def collect_frequent_files(
    records: list[dict[str, Any]],
    *,
    root: Path | None = None,
    now: datetime | None = None,
    window_seconds: int = WINDOW_SECONDS,
    min_count: int = MIN_COUNT,
    engine: RuleEngine | None = None,
    watch_id: str = "",
) -> list[dict[str, Any]]:
    wall = now if now is not None else datetime.now(timezone.utc)
    if wall.tzinfo is None:
        wall = wall.replace(tzinfo=timezone.utc)
    start = wall - timedelta(seconds=max(window_seconds, 1))
    visible = countable_event_records(records)
    buckets: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = defaultdict(int)
    for record in visible:
        if record.get("is_dir"):
            continue
        raw_path = record.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        ts = parse_event_ts(record.get("ts"))
        if ts is None or ts < start or ts > wall + timedelta(seconds=5):
            continue
        key = path_key(raw_path)
        counts[key] += 1
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = {
                "path": raw_path,
                "rel": event_rel(root, raw_path),
                "last_ts": record.get("ts"),
            }
        else:
            bucket["path"] = raw_path
            bucket["last_ts"] = record.get("ts")
    items: list[dict[str, Any]] = []
    for key, count in counts.items():
        if count < min_count:
            continue
        meta = buckets[key]
        path = str(meta["path"])
        if engine is not None and _already_excluded(engine, path, watch_id=watch_id, now=wall):
            continue
        items.append(
            {
                "path": path,
                "rel": meta["rel"],
                "count": count,
                "window_seconds": window_seconds,
            }
        )
    items.sort(key=lambda item: (-int(item["count"]), str(item["rel"])))
    return items[:MAX_CANDIDATES]


def _already_excluded(engine: RuleEngine, path: str, *, watch_id: str, now: datetime) -> bool:
    event = FileEvent(
        id="frequent-probe",
        ts=now.isoformat(),
        watch_id=watch_id,
        type="modified",
        path=path,
        is_dir=False,
    )
    return bool(engine.exclude_hits(event, now=now))


def exclude_rule_dict(name: str, globs: list[str]) -> dict[str, Any]:
    unique: list[str] = []
    seen: set[str] = set()
    for glob in globs:
        text = to_posix(glob).strip().lstrip("./")
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    if not unique:
        raise ValueError("globs")
    return {
        "name": name,
        "enabled": True,
        "exclude": True,
        "when": {
            "types": list(EVENT_TYPES),
            "glob": unique,
            "regex": None,
            "is_dir": False,
            "min_size_bytes": None,
            "cooldown_seconds": 0,
            "active": None,
        },
        "then": [],
    }
