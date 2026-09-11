from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from filewatch.paths import watcher_dir, watchers_root


class WatchStore:
    def __init__(self, watch_id: str, root: Path | None = None) -> None:
        self.watch_id = watch_id
        self.dir = (root / watch_id) if root is not None else watcher_dir(watch_id)
        self.events_path = self.dir / "events.jsonl"
        self.jobs_path = self.dir / "jobs.jsonl"
        self.cursors_path = self.dir / "cursors.json"
        self.pid_path = self.dir / "daemon.pid"
        self.log_path = self.dir / "daemon.log"
        self.stop_path = self.dir / "stop.flag"
        self.config_path = self.dir / "config.json"

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        self.jobs_path.touch(exist_ok=True)
        if not self.cursors_path.exists():
            self.write_cursors({"events": 0, "jobs": 0})

    def stream_path(self, stream: str) -> Path:
        if stream == "events":
            return self.events_path
        if stream == "jobs":
            return self.jobs_path
        raise ValueError(f"unknown stream: {stream}")

    def append(self, stream: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure()
        path = self.stream_path(stream)
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return payload

    def read_since(self, stream: str, offset: int, limit: int | None = None) -> tuple[list[dict[str, Any]], int]:
        path = self.stream_path(stream)
        if not path.exists():
            return [], 0
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(max(offset, 0))
            consumed = handle.tell()
            while True:
                pos = handle.tell()
                line = handle.readline()
                if line == "":
                    break
                if not line.endswith("\n"):
                    break
                consumed = handle.tell()
                stripped = line.strip()
                if not stripped:
                    continue
                records.append(json.loads(stripped))
                if limit is not None and len(records) >= limit:
                    break
            if limit is not None and len(records) >= limit:
                return records, consumed
            return records, consumed

    def wait(
        self,
        stream: str,
        offset: int,
        timeout: float,
        limit: int = 50,
        poll: float = 0.2,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        deadline = time.monotonic() + max(timeout, 0)
        while True:
            records, cursor = self.read_since(stream, offset, limit)
            if records:
                return records, cursor, False
            if time.monotonic() >= deadline:
                return [], offset, True
            time.sleep(poll)

    def read_cursors(self) -> dict[str, int]:
        if not self.cursors_path.exists():
            return {"events": 0, "jobs": 0}
        data = json.loads(self.cursors_path.read_text(encoding="utf-8"))
        return {"events": int(data.get("events", 0)), "jobs": int(data.get("jobs", 0))}

    def write_cursors(self, cursors: dict[str, int]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cursors_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cursors), encoding="utf-8")
        tmp.replace(self.cursors_path)

    def ack(self, stream: str, cursor: int) -> dict[str, int]:
        cursors = self.read_cursors()
        if cursor < cursors.get(stream, 0):
            raise ValueError("cursor cannot move backwards")
        cursors[stream] = cursor
        self.write_cursors(cursors)
        return cursors

    def pending_count(self, stream: str) -> int:
        cursors = self.read_cursors()
        records, _ = self.read_since(stream, cursors.get(stream, 0))
        return len(records)

    def write_pid(self, pid: int) -> None:
        self.ensure()
        self.pid_path.write_text(str(pid), encoding="utf-8")

    def read_pid(self) -> int | None:
        if not self.pid_path.exists():
            return None
        text = self.pid_path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        return int(text)

    def request_stop(self) -> None:
        self.ensure()
        self.stop_path.write_text("1", encoding="utf-8")

    def clear_stop(self) -> None:
        if self.stop_path.exists():
            self.stop_path.unlink()

    def stop_requested(self) -> bool:
        return self.stop_path.exists()


def list_stores() -> list[WatchStore]:
    root = watchers_root()
    if not root.exists():
        return []
    stores = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "config.json").exists():
            stores.append(WatchStore(child.name, root=root))
    return stores
