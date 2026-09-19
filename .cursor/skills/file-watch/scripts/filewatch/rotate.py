"""按本地日期切分状态文件，并丢掉超过保留期的旧文件。"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

DEFAULT_KEEP_DAYS = 14
MAX_KEEP_DAYS = 365
CURSOR_EPOCH = date(2020, 1, 1)
# 单日文件上限 100GB；编码后的游标仍落在 JS 安全整数内。
CURSOR_SPAN = 100_000_000_000
_STREAM_NAME = re.compile(r"^(events|jobs)-(\d{4}-\d{2}-\d{2})\.jsonl$")
_DAEMON_NAME = re.compile(r"^daemon-(\d{4}-\d{2}-\d{2})\.log$")


def clamp_keep_days(value: Any, default: int = DEFAULT_KEEP_DAYS) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(days, MAX_KEEP_DAYS))


def keep_days(env: dict[str, str] | None = None) -> int:
    try:
        from filewatch.settings import stored_log_keep_days

        stored = stored_log_keep_days()
        if stored is not None:
            return stored
    except Exception:
        pass
    source = os.environ if env is None else env
    raw = source.get("FILEWATCH_LOG_KEEP_DAYS")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_KEEP_DAYS
    return clamp_keep_days(raw)


def local_now(clock: Callable[[], datetime] | None = None) -> datetime:
    if clock is not None:
        current = clock()
        if current.tzinfo is None:
            return current.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return current
    return datetime.now().astimezone()


def local_date(clock: Callable[[], datetime] | None = None) -> date:
    return local_now(clock).date()


def file_mtime_date(path: Path) -> date:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return local_date()
    return datetime.fromtimestamp(stamp).astimezone().date()


def encode_cursor(day: date, offset: int) -> int:
    serial = (day - CURSOR_EPOCH).days
    if serial < 0:
        serial = 0
    pos = max(0, int(offset))
    if pos >= CURSOR_SPAN:
        pos = CURSOR_SPAN - 1
    return serial * CURSOR_SPAN + pos


def decode_cursor(cursor: int) -> tuple[date, int]:
    value = max(0, int(cursor or 0))
    serial, offset = divmod(value, CURSOR_SPAN)
    return CURSOR_EPOCH + timedelta(days=serial), offset


def stream_file(directory: Path, stream: str, day: date) -> Path:
    return directory / f"{stream}-{day.isoformat()}.jsonl"


def daemon_file(directory: Path, day: date) -> Path:
    return directory / f"daemon-{day.isoformat()}.log"


def list_stream_files(directory: Path, stream: str) -> list[tuple[date, Path]]:
    if not directory.exists():
        return []
    items: list[tuple[date, Path]] = []
    legacy = directory / f"{stream}.jsonl"
    if legacy.exists():
        items.append((file_mtime_date(legacy), legacy))
    for child in directory.iterdir():
        match = _STREAM_NAME.fullmatch(child.name)
        if match and match.group(1) == stream:
            items.append((date.fromisoformat(match.group(2)), child))
    items.sort(key=lambda item: (item[0], item[1].name))
    return items


def list_daemon_files(directory: Path) -> list[tuple[date, Path]]:
    if not directory.exists():
        return []
    items: list[tuple[date, Path]] = []
    legacy = directory / "daemon.log"
    if legacy.exists():
        items.append((file_mtime_date(legacy), legacy))
    for child in directory.iterdir():
        match = _DAEMON_NAME.fullmatch(child.name)
        if match:
            items.append((date.fromisoformat(match.group(1)), child))
    items.sort(key=lambda item: (item[0], item[1].name))
    return items


def _replace_or_merge(src: Path, dest: Path) -> None:
    if src.resolve() == dest.resolve():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        data = src.read_bytes() + dest.read_bytes()
        dest.write_bytes(data)
        src.unlink()
        return
    src.replace(dest)


def migrate_legacy_stream(directory: Path, stream: str) -> None:
    legacy = directory / f"{stream}.jsonl"
    if not legacy.exists():
        return
    try:
        empty = legacy.stat().st_size == 0
    except OSError:
        return
    if empty:
        legacy.unlink(missing_ok=True)
        return
    dest = stream_file(directory, stream, file_mtime_date(legacy))
    _replace_or_merge(legacy, dest)


def migrate_legacy_daemon(directory: Path) -> None:
    legacy = directory / "daemon.log"
    if not legacy.exists():
        return
    try:
        empty = legacy.stat().st_size == 0
    except OSError:
        return
    if empty:
        legacy.unlink(missing_ok=True)
        return
    dest = daemon_file(directory, file_mtime_date(legacy))
    _replace_or_merge(legacy, dest)


def remap_legacy_cursor(directory: Path, stream: str, offset: int) -> int:
    if offset <= 0:
        return 0
    remaining = int(offset)
    files = list_stream_files(directory, stream)
    if not files:
        return 0
    for day, path in files:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if remaining <= size:
            return encode_cursor(day, remaining)
        remaining -= size
    last_day, last_path = files[-1]
    try:
        size = last_path.stat().st_size
    except OSError:
        size = 0
    return encode_cursor(last_day, size)


def event_ids_in_file(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.exists():
        return ids
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                event_id = record.get("id")
                if isinstance(event_id, str) and event_id:
                    ids.add(event_id)
    return ids


def prune_dated_files(
    directory: Path,
    *,
    keep: int,
    today: date | None = None,
) -> set[str]:
    """删除过期的按日文件。返回从过期 events 文件里收集到的 event id。"""
    if not directory.exists():
        return set()
    wall = today or local_date()
    cutoff = wall - timedelta(days=keep - 1)
    dropped_ids: set[str] = set()
    for day, path in list_stream_files(directory, "events"):
        if day < cutoff:
            dropped_ids.update(event_ids_in_file(path))
            path.unlink(missing_ok=True)
    for stream in ("jobs",):
        for day, path in list_stream_files(directory, stream):
            if day < cutoff:
                path.unlink(missing_ok=True)
    for day, path in list_daemon_files(directory):
        if day < cutoff:
            path.unlink(missing_ok=True)
    return dropped_ids


def read_log_tail(directory: Path, size: int = 2000) -> str:
    remaining = max(0, int(size))
    if remaining == 0:
        return ""
    chunks: list[str] = []
    for _day, path in reversed(list_daemon_files(directory)):
        if remaining <= 0:
            break
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if len(text) > remaining:
            chunks.append(text[-remaining:])
            remaining = 0
        else:
            chunks.append(text)
            remaining -= len(text)
    return "".join(reversed(chunks))


def prune_agent_logs(log_dir: Path, *, keep: int, now: datetime | None = None) -> None:
    if not log_dir.exists():
        return
    wall = now or local_now()
    if wall.tzinfo is None:
        wall = wall.replace(tzinfo=timezone.utc)
    cutoff = wall - timedelta(days=keep)
    from filewatch.agent.logging import read_index, write_index

    data = read_index(log_dir)
    kept: list[dict[str, Any]] = []
    kept_ids: set[str] = set()
    for job in data.get("jobs", []):
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("job_id") or "")
        path = log_dir / f"{job_id}.jsonl" if job_id else None
        if str(job.get("status") or "") == "running":
            kept.append(job)
            if job_id:
                kept_ids.add(job_id)
            continue
        stamp = _job_stamp(job, path)
        if stamp is not None and stamp < cutoff:
            if path is not None:
                path.unlink(missing_ok=True)
            continue
        kept.append(job)
        if job_id:
            kept_ids.add(job_id)
    write_index(log_dir, {"jobs": kept})
    for path in log_dir.glob("job_*.jsonl"):
        if path.stem in kept_ids:
            continue
        stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if stamp.astimezone() < cutoff:
            path.unlink(missing_ok=True)


def _job_stamp(job: dict[str, Any], path: Path | None) -> datetime | None:
    for key in ("ended_ts", "ts"):
        raw = job.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone()
    if path is not None and path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    return None


class DailyFileStream:
    """按本地日期滚动的文本流，供守护进程 stdout/stderr 和 logging 使用。"""

    def __init__(
        self,
        directory: Path,
        prefix: str = "daemon",
        suffix: str = ".log",
        *,
        clock: Callable[[], datetime] | None = None,
        redirect_std: bool = False,
    ) -> None:
        self.directory = directory
        self.prefix = prefix
        self.suffix = suffix
        self.clock = clock
        self.redirect_std = redirect_std
        self.encoding = "utf-8"
        self.errors = "replace"
        self._lock = threading.Lock()
        self._day: date | None = None
        self._file: TextIO | None = None
        self._reopen_locked()

    @property
    def name(self) -> str:
        if self._file is not None:
            return getattr(self._file, "name", "")
        return ""

    def fileno(self) -> int:
        if self._file is None:
            raise OSError("stream is closed")
        return self._file.fileno()

    def isatty(self) -> bool:
        return False

    def readable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False

    def write(self, data: str) -> int:
        if not data:
            return 0
        with self._lock:
            self._reopen_locked()
            assert self._file is not None
            self._file.write(data)
            self._file.flush()
        return len(data)

    def flush(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.flush()

    def reopen_if_needed(self) -> None:
        with self._lock:
            self._reopen_locked()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
                self._day = None

    def _reopen_locked(self) -> None:
        today = local_date(self.clock)
        if self._day == today and self._file is not None:
            return
        if self._file is not None:
            self._file.close()
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{self.prefix}-{today.isoformat()}{self.suffix}"
        self._file = path.open("a", encoding="utf-8")
        self._day = today
        if self.redirect_std:
            try:
                os.dup2(self._file.fileno(), 1)
                os.dup2(self._file.fileno(), 2)
            except OSError:
                pass


def install_daemon_logging(
    directory: Path,
    *,
    clock: Callable[[], datetime] | None = None,
    redirect_std: bool = True,
) -> DailyFileStream:
    directory.mkdir(parents=True, exist_ok=True)
    stream = DailyFileStream(directory, clock=clock, redirect_std=redirect_std)
    sys.stdout = stream
    sys.stderr = stream
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=stream,
        force=True,
    )
    return stream
