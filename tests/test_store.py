from __future__ import annotations

from filewatch.store import WatchStore


def test_append_wait_ack(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.append("events", {"id": "1", "path": "a.txt"})
    items, cursor, timed_out = store.wait("events", 0, timeout=0.1, limit=10)
    assert not timed_out
    assert len(items) == 1
    assert items[0]["id"] == "1"
    store.ack("events", cursor)
    empty, _, timed_out = store.wait("events", store.read_cursors()["events"], timeout=0, limit=10)
    assert timed_out
    assert empty == []


def test_incomplete_last_line_is_not_consumed(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.events_path.write_text('{"id":"1"}\n{"id":"partial"', encoding="utf-8")
    items, cursor = store.read_since("events", 0)
    assert [item["id"] for item in items] == ["1"]
    store.events_path.write_text('{"id":"1"}\n{"id":"2"}\n', encoding="utf-8")
    items, _ = store.read_since("events", cursor)
    assert [item["id"] for item in items] == ["2"]
