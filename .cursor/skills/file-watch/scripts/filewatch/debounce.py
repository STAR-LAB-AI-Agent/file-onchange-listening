from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from filewatch.models import FileEvent


def coalesce_types(types: set[str]) -> str:
    if "moved" in types:
        return "moved"
    if "created" in types and "deleted" in types:
        return "modified"
    if "created" in types:
        return "created"
    if "deleted" in types:
        return "deleted"
    return "modified"


@dataclass
class _Pending:
    event: FileEvent
    types: set[str] = field(default_factory=set)
    due: float = 0.0


class Debouncer:
    """Per-path coalesce with a single worker thread.

    Watchdog's EventDebouncer waits for a global quiet period then delivers
    the whole burst. That is right for "rebuild once". This watcher needs each
    path to flush when *that* path goes quiet, without creating one
    ``threading.Timer`` per file.
    """

    def __init__(self, delay_ms: int, flush: Callable[[FileEvent], None]) -> None:
        self.delay = max(delay_ms, 0) / 1000.0
        self._flush = flush
        self._cond = threading.Condition()
        self._pending: dict[str, _Pending] = {}
        self._stopped = False
        self._thread = threading.Thread(target=self._run, name="filewatch-debounce", daemon=True)
        self._thread.start()

    def set_delay_ms(self, delay_ms: int) -> None:
        with self._cond:
            self.delay = max(delay_ms, 0) / 1000.0
            now = time.monotonic()
            for item in self._pending.values():
                item.due = now + self.delay
            self._cond.notify()

    def push(self, event: FileEvent) -> None:
        merged: FileEvent | None = None
        with self._cond:
            if self._stopped:
                return
            self._merge(event)
            if self.delay == 0:
                item = self._pending.pop(event.path, None)
                merged = self._merged(item) if item is not None else None
            self._cond.notify()
        if merged is not None:
            self._flush(merged)

    def _merge(self, event: FileEvent) -> None:
        item = self._pending.get(event.path)
        if item is None:
            item = _Pending(event=event, types={event.type})
            self._pending[event.path] = item
        else:
            item.types.add(event.type)
            if event.type == "moved":
                item.event = event
            else:
                item.event = FileEvent(
                    id=event.id,
                    ts=event.ts,
                    watch_id=event.watch_id,
                    type=event.type,
                    path=event.path,
                    old_path=item.event.old_path or event.old_path,
                    is_dir=event.is_dir,
                )
        item.due = time.monotonic() + self.delay

    def _merged(self, item: _Pending) -> FileEvent:
        event = item.event
        return FileEvent(
            id=event.id,
            ts=event.ts,
            watch_id=event.watch_id,
            type=coalesce_types(item.types),
            path=event.path,
            old_path=event.old_path,
            is_dir=event.is_dir,
        )

    def _run(self) -> None:
        while True:
            with self._cond:
                if self._stopped:
                    return
                if not self._pending:
                    self._cond.wait()
                    continue
                key = min(self._pending, key=lambda item: self._pending[item].due)
                wait = self._pending[key].due - time.monotonic()
                if wait > 0:
                    self._cond.wait(timeout=wait)
                    continue
                item = self._pending.pop(key)
            self._flush(self._merged(item))

    def flush_all(self) -> None:
        with self._cond:
            items = list(self._pending.values())
            self._pending.clear()
        for item in items:
            self._flush(self._merged(item))

    def close(self) -> None:
        self.flush_all()
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        self._thread.join(timeout=2)

    def cancel(self) -> None:
        with self._cond:
            self._pending.clear()
            self._stopped = True
            self._cond.notify_all()
        self._thread.join(timeout=2)
