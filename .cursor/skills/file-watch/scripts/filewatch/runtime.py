from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from filewatch.actions import ActionRunner
from filewatch.config import config_to_dict
from filewatch.debounce import Debouncer
from filewatch.matching import path_is_ignored
from filewatch.models import EVENT_TYPES, Config, FileEvent
from filewatch.rules import RuleEngine
from filewatch.store import WatchStore

log = logging.getLogger("filewatch")

# Drop dir-modified / open / close at the emitter. Windows ReadDirectoryChangesW
# emits DirModifiedEvent constantly; Linux inotify adds opened/closed.
WATCHED_EVENT_TYPES = [
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    DirCreatedEvent,
    DirDeletedEvent,
    DirMovedEvent,
]


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def decode_watchdog_path(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return os.fsdecode(value)
    text = str(value).strip()
    return text


class WatchRuntime:
    def __init__(self, config: Config, store: WatchStore) -> None:
        self.config = config
        self.store = store
        self.root = Path(config.watch.path).resolve()
        self.engine = RuleEngine(self.root, config.rules)
        self.actions = ActionRunner(store, max_workers=config.max_parallel_jobs)
        self.debouncer = Debouncer(config.watch.debounce_ms, self._on_coalesced)
        self.observer = Observer()
        self._ignore_case = sys.platform == "win32"
        self._stop = threading.Event()

    def start(self) -> None:
        if not self.root.exists() or not self.root.is_dir():
            raise FileNotFoundError(f"watch path is not a directory: {self.root}")
        self.store.ensure()
        self.store.clear_stop()
        self.store.config_path.write_text(
            json.dumps(config_to_dict(self.config), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.store.write_pid(os.getpid())
        handler = _Handler(self)
        schedule_kwargs: dict = {"recursive": self.config.watch.recursive}
        try:
            self.observer.schedule(
                handler,
                str(self.root),
                event_filter=WATCHED_EVENT_TYPES,
                **schedule_kwargs,
            )
        except TypeError:
            self.observer.schedule(handler, str(self.root), **schedule_kwargs)
        self.observer.start()
        log.info("watching %s id=%s", self.root, self.store.watch_id)

    def stop(self) -> None:
        self._stop.set()
        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=5)
        self.debouncer.close()
        self.actions.close(wait=False)
        if self.store.pid_path.exists():
            self.store.pid_path.unlink()

    def run_forever(self, poll: float = 0.4) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                if self.store.stop_requested():
                    log.info("stop flag detected")
                    break
                time.sleep(poll)
        finally:
            self.stop()

    def _is_state_path(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            store = self.store.dir.resolve()
        except OSError:
            return False
        return resolved == store or store in resolved.parents

    def handle_raw(self, fs_event: FileSystemEvent) -> None:
        event_type = getattr(fs_event, "event_type", None)
        is_dir = bool(getattr(fs_event, "is_directory", False))
        if event_type not in EVENT_TYPES:
            return
        if event_type == "modified" and is_dir:
            return
        src = decode_watchdog_path(fs_event.src_path)
        dest = decode_watchdog_path(getattr(fs_event, "dest_path", "") or "")
        path_str = dest or src
        if not path_str:
            return
        path = Path(path_str)
        if self._is_state_path(path):
            return
        if dest:
            old = Path(src) if src else None
            if old is not None and self._is_state_path(old):
                return
        if path_is_ignored(self.root, path, self.config.watch.ignore, ignore_case=self._ignore_case):
            return
        old_path = src if event_type == "moved" and src and src != path_str else None
        event = FileEvent(
            id=new_id("evt"),
            ts=utc_now(),
            watch_id=self.store.watch_id,
            type=str(event_type),
            path=str(path),
            old_path=old_path,
            is_dir=is_dir,
        )
        self.debouncer.push(event)

    def _on_coalesced(self, event: FileEvent) -> None:
        self.store.append("events", event.to_dict())
        log.info("event %s %s", event.type, event.path)
        for rule in self.engine.matches(event):
            log.info("rule hit %s -> %s", rule.name, event.path)
            self.actions.submit(event, rule)


class _Handler(FileSystemEventHandler):
    def __init__(self, runtime: WatchRuntime) -> None:
        self.runtime = runtime

    def on_any_event(self, event: FileSystemEvent) -> None:
        self.runtime.handle_raw(event)
