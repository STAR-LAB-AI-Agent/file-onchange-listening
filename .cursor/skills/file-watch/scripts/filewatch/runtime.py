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
from filewatch.config import ConfigError, config_to_dict, parse_config_dict, summarize_config
from filewatch.debounce import Debouncer
from filewatch.matching import path_is_ignored
from filewatch.models import EVENT_TYPES, Config, FileEvent
from filewatch.rules import RuleEngine
from filewatch.store import WatchStore

log = logging.getLogger("filewatch")


class ReloadError(Exception):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message

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
        self._config_lock = threading.Lock()

    def start(self) -> None:
        if not self.root.exists() or not self.root.is_dir():
            raise FileNotFoundError(f"watch path is not a directory: {self.root}")
        self.store.ensure()
        self.store.clear_stop()
        self.store.clear_reload()
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
                if not self._poll_control():
                    log.info("stop flag detected")
                    break
                time.sleep(poll)
        finally:
            self.stop()

    def _poll_control(self) -> bool:
        if self.store.stop_requested():
            return False
        if self.store.reload_requested():
            self._handle_reload()
        return True

    def apply_reload(self, config: Config) -> dict:
        new_root = Path(config.watch.path).resolve()
        if new_root != self.root:
            raise ReloadError("needs_restart", "监听路径变更需要重启，无法热更新")
        if bool(config.watch.recursive) != bool(self.config.watch.recursive):
            raise ReloadError("needs_restart", "recursive 变更需要重启，无法热更新")
        warnings: list[str] = []
        with self._config_lock:
            old_parallel = self.config.max_parallel_jobs
            self.engine.replace_rules(config.rules)
            self.debouncer.set_delay_ms(config.watch.debounce_ms)
            self.config = Config(
                name=self.config.name,
                watch=config.watch,
                rules=config.rules,
                max_parallel_jobs=old_parallel,
                source=config.source,
            )
        if config.max_parallel_jobs != old_parallel:
            warnings.append("max_parallel_jobs 未热更新，需重启后生效")
        summary = summarize_config(self.config)
        summary["warnings"] = warnings
        return summary

    def _handle_reload(self) -> None:
        generation = ""
        try:
            generation, pending = self.store.read_pending_config()
            config = parse_config_dict(pending, source=pending.get("source"))
            config = Config(
                name=self.config.name,
                watch=config.watch,
                rules=config.rules,
                max_parallel_jobs=config.max_parallel_jobs,
                source=config.source,
            )
            result = self.apply_reload(config)
            self.store.config_path.write_text(
                json.dumps(config_to_dict(self.config), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.store.write_reload_status(
                {
                    "ok": True,
                    "generation": generation,
                    "watch_id": self.store.watch_id,
                    "rules": [rule["name"] for rule in result["rules"]],
                    "warnings": result["warnings"],
                    "applied": result,
                }
            )
            log.info("reloaded rules=%s", [rule["name"] for rule in result["rules"]])
        except ReloadError as exc:
            self.store.write_reload_status(
                {
                    "ok": False,
                    "generation": generation,
                    "error": exc.error,
                    "message": exc.message,
                }
            )
            log.warning("reload rejected: %s", exc.message)
        except (ConfigError, ValueError, FileNotFoundError) as exc:
            self.store.write_reload_status(
                {
                    "ok": False,
                    "generation": generation,
                    "error": "bad_config",
                    "message": str(exc),
                }
            )
            log.warning("reload failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            self.store.write_reload_status(
                {
                    "ok": False,
                    "generation": generation,
                    "error": "reload_failed",
                    "message": str(exc),
                }
            )
            log.exception("reload failed")
        finally:
            self.store.clear_reload()

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
        with self._config_lock:
            ignore = self.config.watch.ignore
        if path_is_ignored(self.root, path, ignore, ignore_case=self._ignore_case):
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
        with self._config_lock:
            hits = self.engine.matches(event)
        for rule in hits:
            log.info("rule hit %s -> %s", rule.name, event.path)
            self.actions.submit(event, rule)


class _Handler(FileSystemEventHandler):
    def __init__(self, runtime: WatchRuntime) -> None:
        self.runtime = runtime

    def on_any_event(self, event: FileSystemEvent) -> None:
        self.runtime.handle_raw(event)
