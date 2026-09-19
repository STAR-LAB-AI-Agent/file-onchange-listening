from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from filewatch.agent.types import ToolCallRecord

_CST = timezone(timedelta(hours=8))
_CMD_OUTPUT_LIMIT = 4000
_CMD_ARGS_LIMIT = 1500
_TEXT_LIMIT = 8000
_index_locks: dict[str, threading.Lock] = {}
_index_locks_guard = threading.Lock()


def _index_lock(log_dir: Path) -> threading.Lock:
    key = str(log_dir.resolve())
    with _index_locks_guard:
        lock = _index_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _index_locks[key] = lock
        return lock


def now_display_ts() -> str:
    return datetime.now(_CST).strftime("%H:%M:%S")


def now_iso_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clip_text(text: str, limit: int) -> str:
    value = text or ""
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def format_tool_command(name: str, arguments: dict[str, Any] | None = None) -> str:
    args = arguments or {}
    if name in ("Bash", "PowerShell"):
        cmd = str(args.get("command") or args.get("cmd") or "").strip()
        return f"{name} {cmd}".strip() if cmd else name
    compact = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
    return f"{name} {clip_text(compact, _CMD_ARGS_LIMIT)}"


def format_tool_output(result: Any) -> str:
    if isinstance(result, str):
        return clip_text(result, _CMD_OUTPUT_LIMIT)
    try:
        text = json.dumps(result, ensure_ascii=False)
    except TypeError:
        text = str(result)
    return clip_text(text, _CMD_OUTPUT_LIMIT)


def index_path(log_dir: Path) -> Path:
    return log_dir / "index.json"


def read_index(log_dir: Path) -> dict[str, Any]:
    path = index_path(log_dir)
    if not path.exists():
        return {"jobs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"jobs": []}
    if not isinstance(data, dict):
        return {"jobs": []}
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        data["jobs"] = []
    return data


def write_index(log_dir: Path, payload: dict[str, Any]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = index_path(log_dir)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def upsert_job(log_dir: Path, job: dict[str, Any]) -> dict[str, Any]:
    with _index_lock(log_dir):
        data = read_index(log_dir)
        jobs = [item for item in data.get("jobs", []) if isinstance(item, dict)]
        job_id = str(job.get("job_id") or "")
        found = False
        for index, item in enumerate(jobs):
            if str(item.get("job_id") or "") == job_id:
                merged = {**item, **job}
                jobs[index] = merged
                job = merged
                found = True
                break
        if not found:
            session = int(job.get("session") or 0)
            if session <= 0:
                used = [int(item.get("session") or 0) for item in jobs]
                job["session"] = (max(used) if used else 0) + 1
            jobs.append(job)
        jobs.sort(key=lambda item: (int(item.get("session") or 0), str(item.get("ts") or "")))
        write_index(log_dir, {"jobs": jobs})
        return job


class ToolCallLogger:
    def __init__(
        self,
        path: Path,
        *,
        job_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.job_id = job_id or path.stem
        self.log_dir = path.parent
        self.meta = dict(meta or {})
        self._lock = threading.Lock()
        self._seq = _count_lines(path)
        self._closed = False
        registered = upsert_job(
            self.log_dir,
            {
                "job_id": self.job_id,
                "ts": now_iso_ts(),
                "status": "running",
                "rule": self.meta.get("rule"),
                "path": self.meta.get("path"),
                "type": self.meta.get("type"),
                "watch_id": self.meta.get("watch_id"),
            },
        )
        self.session = int(registered.get("session") or 1)

    def emit(self, kind: str, **fields: Any) -> dict[str, Any]:
        event: dict[str, Any] = {
            "kind": kind,
            "ts": now_display_ts(),
            "ts_iso": now_iso_ts(),
            "job_id": self.job_id,
            "session": self.session,
        }
        if self.meta.get("rule"):
            event["role"] = self.meta["rule"]
        for key, value in fields.items():
            if value is not None:
                event[key] = value
        text = event.get("text")
        if isinstance(text, str):
            event["text"] = clip_text(text, _TEXT_LIMIT)
        with self._lock:
            self._seq += 1
            event["seq"] = self._seq
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def log(self, record: ToolCallRecord) -> None:
        command = format_tool_command(record.name, record.arguments)
        output = format_tool_output(record.result.to_dict())
        ok = record.result.ok
        kind = "cmd" if ok else "tool_exec_error"
        self.emit(
            kind,
            tool=record.name,
            tool_call_id=record.id,
            command=command,
            output=output,
            exit_code=0 if ok else 1,
            duration_ms=round(record.duration_ms, 2),
            ok=ok,
            input=record.arguments,
            text=None if ok else (record.result.message or record.result.error or output),
        )

    def close(self, status: str, text: str | None = None) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if text:
            self.emit("system" if status == "ok" else "error", text=text)
        if status != "ok" and text:
            self.emit("system", text=f"已结束：{status}")
        upsert_job(
            self.log_dir,
            {
                "job_id": self.job_id,
                "status": status,
                "ended_ts": now_iso_ts(),
            },
        )


def _count_lines(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for _ in handle:
            count += 1
    return count
