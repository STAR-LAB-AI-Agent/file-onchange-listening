from __future__ import annotations

import time

from filewatch.debounce import Debouncer, coalesce_types
from filewatch.models import FileEvent
from filewatch.runtime import decode_watchdog_path


def _event(path: str, event_type: str = "modified") -> FileEvent:
    return FileEvent(
        id="evt_1",
        ts="2026-01-01T00:00:00Z",
        watch_id="demo",
        type=event_type,
        path=path,
        is_dir=False,
    )


def test_coalesce_created_and_modified() -> None:
    assert coalesce_types({"created", "modified"}) == "created"


def test_coalesce_deleted_and_created() -> None:
    assert coalesce_types({"deleted", "created"}) == "modified"


def test_coalesce_moved() -> None:
    assert coalesce_types({"moved", "modified"}) == "moved"


def test_per_path_debounce_flushes_after_quiet_period() -> None:
    seen: list[FileEvent] = []
    debouncer = Debouncer(80, seen.append)
    try:
        debouncer.push(_event("a.txt", "created"))
        debouncer.push(_event("a.txt", "modified"))
        debouncer.push(_event("b.txt", "created"))
        assert seen == []
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and len(seen) < 2:
            time.sleep(0.02)
        assert {item.path: item.type for item in seen} == {"a.txt": "created", "b.txt": "created"}
    finally:
        debouncer.close()


def test_delay_zero_flushes_immediately() -> None:
    seen: list[FileEvent] = []
    debouncer = Debouncer(0, seen.append)
    try:
        debouncer.push(_event("a.txt", "modified"))
        assert [item.path for item in seen] == ["a.txt"]
    finally:
        debouncer.close()


def test_decode_watchdog_path_accepts_bytes() -> None:
    assert decode_watchdog_path(b"hello.txt") == "hello.txt"
    assert decode_watchdog_path("") == ""
    assert decode_watchdog_path(None) == ""
