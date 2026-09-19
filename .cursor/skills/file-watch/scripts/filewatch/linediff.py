"""Text-file line diffs against per-path snapshots under the watcher state dir."""

from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from filewatch.models import DEFAULT_LINE_DIFF_MAX_BYTES

MAX_FILE_BYTES = DEFAULT_LINE_DIFF_MAX_BYTES
NUL_PROBE_BYTES = 8 * 1024
MAX_CHANGE_ROWS = 80
MAX_LINE_CHARS = 200
ENCODINGS = ("utf-8-sig", "utf-8", "gbk")


def path_key(path: str | Path) -> str:
    text = str(Path(path))
    try:
        text = str(Path(path).resolve())
    except OSError:
        pass
    return hashlib.sha256(text.encode("utf-8", errors="surrogateescape")).hexdigest()


def snapshot_path(snapshots_dir: Path, path: str | Path) -> Path:
    return snapshots_dir / f"{path_key(path)}.txt"


def _truncate_line(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_LINE_CHARS:
        return text, False
    return text[:MAX_LINE_CHARS], True


def split_lines(text: str) -> list[str]:
    if not text:
        return []
    return text.splitlines()


def decode_bytes(raw: bytes) -> tuple[str, str] | None:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding if encoding != "utf-8-sig" else "utf-8"
        except UnicodeDecodeError:
            continue
    return None


def content_fingerprint(path: Path, *, max_bytes: int = MAX_FILE_BYTES) -> str | None:
    """Stable identity for skip-if-unchanged. None if the file cannot be read."""
    skipped, text, _encoding = read_text_file(path, max_bytes=max_bytes)
    if skipped is None and text is not None:
        return "t:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    try:
        if not path.is_file():
            return None
        stat = path.stat()
        if stat.st_size > max_bytes:
            mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
            return f"m:{stat.st_size}:{mtime_ns}"
        return "b:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def snapshot_fingerprint(snapshots_dir: Path, path: str | Path) -> str | None:
    baseline = load_snapshot(snapshots_dir, path)
    if baseline is None:
        return None
    return "t:" + hashlib.sha256(baseline.encode("utf-8")).hexdigest()


def is_pending_line_changes(record: dict[str, Any]) -> bool:
    payload = record.get("line_changes")
    return isinstance(payload, dict) and payload.get("kind") == "pending"


def is_noop_text_modified(record: dict[str, Any]) -> bool:
    """True when a modified event settled to zero line changes."""
    if record.get("type") != "modified":
        return False
    payload = record.get("line_changes")
    if not isinstance(payload, dict) or payload.get("kind") != "text":
        return False
    return int(payload.get("added") or 0) == 0 and int(payload.get("removed") or 0) == 0


def drop_superseded_pending_modified(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop pending modified events that a later same-path event replaced."""
    latest_by_path: dict[str, int] = {}
    for index, record in enumerate(records):
        path = record.get("path")
        if isinstance(path, str) and path:
            latest_by_path[path] = index
    kept: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        path = record.get("path")
        if (
            record.get("type") == "modified"
            and is_pending_line_changes(record)
            and isinstance(path, str)
            and latest_by_path.get(path) != index
        ):
            continue
        kept.append(record)
    return kept


def read_text_file(path: Path, *, max_bytes: int = MAX_FILE_BYTES) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Return (skipped_payload, text, encoding)."""
    try:
        if not path.exists() or path.is_dir():
            return {"kind": "skipped", "reason": "unreadable"}, None, None
        size = path.stat().st_size
        if size > max_bytes:
            return {"kind": "skipped", "reason": "too_large"}, None, None
        raw = path.read_bytes()
    except OSError:
        return {"kind": "skipped", "reason": "unreadable"}, None, None
    probe = raw[:NUL_PROBE_BYTES]
    if b"\x00" in probe:
        return {"kind": "skipped", "reason": "binary"}, None, None
    decoded = decode_bytes(raw)
    if decoded is None:
        return {"kind": "skipped", "reason": "unreadable"}, None, None
    text, encoding = decoded
    return None, text, encoding


def load_snapshot(snapshots_dir: Path, path: str | Path) -> str | None:
    snap = snapshot_path(snapshots_dir, path)
    if not snap.exists():
        return None
    try:
        return snap.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def write_snapshot(snapshots_dir: Path, path: str | Path, text: str) -> None:
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snap = snapshot_path(snapshots_dir, path)
    tmp = snap.with_suffix(".tmp")
    # Binary write avoids Windows newline translation corrupting \\r\\n.
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(snap)


def delete_snapshot(snapshots_dir: Path, path: str | Path) -> None:
    snap = snapshot_path(snapshots_dir, path)
    if snap.exists():
        try:
            snap.unlink()
        except OSError:
            pass


def move_snapshot(snapshots_dir: Path, old_path: str | Path, new_path: str | Path) -> None:
    old_snap = snapshot_path(snapshots_dir, old_path)
    new_snap = snapshot_path(snapshots_dir, new_path)
    if not old_snap.exists():
        return
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    try:
        if new_snap.exists() and new_snap != old_snap:
            new_snap.unlink()
        old_snap.replace(new_snap)
    except OSError:
        pass


def build_line_changes(
    old_text: str | None,
    new_text: str | None,
    *,
    encoding: str | None = None,
) -> dict[str, Any]:
    old_lines = split_lines(old_text or "")
    new_lines = split_lines(new_text or "")
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    changes: list[dict[str, Any]] = []
    added = 0
    removed = 0
    truncated = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in {"delete", "replace"}:
            for idx in range(i1, i2):
                removed += 1
                if len(changes) < MAX_CHANGE_ROWS:
                    text, cut = _truncate_line(old_lines[idx])
                    truncated = truncated or cut
                    changes.append({"op": "del", "line": idx + 1, "text": text})
                else:
                    truncated = True
        if tag in {"insert", "replace"}:
            for idx in range(j1, j2):
                added += 1
                if len(changes) < MAX_CHANGE_ROWS:
                    text, cut = _truncate_line(new_lines[idx])
                    truncated = truncated or cut
                    changes.append({"op": "add", "line": idx + 1, "text": text})
                else:
                    truncated = True
    payload: dict[str, Any] = {
        "kind": "text",
        "added": added,
        "removed": removed,
        "truncated": truncated,
        "changes": changes,
    }
    if encoding:
        payload["encoding"] = encoding
    return payload


def settle_line_changes(
    snapshots_dir: Path,
    *,
    event_type: str,
    path: str,
    old_path: str | None,
    is_dir: bool,
    max_bytes: int = MAX_FILE_BYTES,
) -> dict[str, Any] | None:
    """Compute final line_changes for a coalesced quiet-window event.

    Returns None for directories (omit field). Otherwise returns text / skipped payload.
    """
    if is_dir:
        return None

    if event_type == "deleted":
        baseline = load_snapshot(snapshots_dir, path)
        if baseline is None and old_path:
            baseline = load_snapshot(snapshots_dir, old_path)
        delete_snapshot(snapshots_dir, path)
        if old_path:
            delete_snapshot(snapshots_dir, old_path)
        if baseline is None:
            return {"kind": "skipped", "reason": "no_baseline"}
        return build_line_changes(baseline, None)

    if event_type == "moved" and old_path:
        move_snapshot(snapshots_dir, old_path, path)

    skipped, text, encoding = read_text_file(Path(path), max_bytes=max_bytes)
    if skipped is not None:
        return skipped
    assert text is not None

    if event_type == "created":
        payload = build_line_changes("", text, encoding=encoding)
        write_snapshot(snapshots_dir, path, text)
        return payload

    baseline = load_snapshot(snapshots_dir, path)
    if baseline is None and event_type == "moved" and old_path:
        baseline = load_snapshot(snapshots_dir, old_path)

    if baseline is None:
        write_snapshot(snapshots_dir, path, text)
        return {"kind": "skipped", "reason": "no_baseline"}

    if baseline == text:
        write_snapshot(snapshots_dir, path, text)
        if event_type == "moved":
            return {
                "kind": "text",
                "encoding": encoding or "utf-8",
                "added": 0,
                "removed": 0,
                "truncated": False,
                "changes": [],
            }
        return {
            "kind": "text",
            "encoding": encoding or "utf-8",
            "added": 0,
            "removed": 0,
            "truncated": False,
            "changes": [],
        }

    payload = build_line_changes(baseline, text, encoding=encoding)
    write_snapshot(snapshots_dir, path, text)
    return payload


def load_line_changes_map(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_line_changes_map(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def drop_line_changes(path: Path, event_ids: set[str]) -> None:
    if not event_ids or not path.exists():
        return
    data = load_line_changes_map(path)
    changed = False
    for event_id in event_ids:
        if event_id in data:
            data.pop(event_id, None)
            changed = True
    if changed:
        save_line_changes_map(path, data)


def put_line_changes(path: Path, event_id: str, payload: dict[str, Any]) -> None:
    data = load_line_changes_map(path)
    data[event_id] = payload
    # Cap growth: keep newest ~2000 entries by dropping arbitrary old keys if huge.
    if len(data) > 2000:
        # Prefer keeping keys that look like event ids; drop extras from the front of sorted keys.
        keys = sorted(data.keys())
        for key in keys[: len(data) - 2000]:
            data.pop(key, None)
    save_line_changes_map(path, data)


def merge_line_changes(record: dict[str, Any], sidecar: dict[str, Any]) -> dict[str, Any]:
    event_id = record.get("id")
    if not isinstance(event_id, str) or event_id not in sidecar:
        return record
    merged = dict(record)
    merged["line_changes"] = sidecar[event_id]
    return merged
