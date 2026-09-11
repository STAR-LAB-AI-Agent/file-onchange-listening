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
        self.reload_flag_path = self.dir / "reload.flag"
        self.pending_path = self.dir / "pending.json"
        self.reload_status_path = self.dir / "reload.status.json"

    def write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None

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

    def read_tail(self, stream: str, limit: int = 200, max_bytes: int = 262144) -> tuple[list[dict[str, Any]], int]:
        path = self.stream_path(stream)
        if not path.exists():
            return [], 0
        size = path.stat().st_size
        with path.open("r", encoding="utf-8") as handle:
            start = max(0, size - max(max_bytes, 1))
            handle.seek(start)
            if start > 0:
                handle.readline()
            records: list[dict[str, Any]] = []
            consumed = handle.tell()
            while True:
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
            if limit is not None and len(records) > limit:
                records = records[-limit:]
            return records, consumed

    def record_count(self, stream: str) -> int:
        path = self.stream_path(stream)
        if not path.exists():
            return 0
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    count += 1
        return count

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

    def request_reload(self, config_dict: dict[str, Any], generation: str) -> None:
        self.ensure()
        if self.reload_status_path.exists():
            self.reload_status_path.unlink()
        self.write_json(self.pending_path, config_dict)
        self.write_json(self.reload_flag_path, {"generation": generation})

    def reload_requested(self) -> bool:
        return self.reload_flag_path.exists()

    def read_pending_config(self) -> tuple[str, dict[str, Any]]:
        flag = self.read_json(self.reload_flag_path) or {}
        generation = str(flag.get("generation") or "")
        pending = self.read_json(self.pending_path)
        if not generation:
            raise ValueError("reload 标志缺少 generation")
        if pending is None:
            raise ValueError("找不到待应用的配置 pending.json")
        return generation, pending

    def write_reload_status(self, payload: dict[str, Any]) -> None:
        self.write_json(self.reload_status_path, payload)

    def read_reload_status(self) -> dict[str, Any] | None:
        return self.read_json(self.reload_status_path)

    def clear_reload(self) -> None:
        for path in (self.reload_flag_path, self.pending_path):
            if path.exists():
                path.unlink()


def list_stores() -> list[WatchStore]:
    root = watchers_root()
    if not root.exists():
        return []
    stores = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "config.json").exists():
            stores.append(WatchStore(child.name, root=root))
    return stores
