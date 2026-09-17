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


def test_read_tail_returns_latest(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    for index in range(5):
        store.append("events", {"id": str(index)})
    items, cursor = store.read_tail("events", limit=2)
    assert [item["id"] for item in items] == ["3", "4"]
    more, _ = store.read_since("events", cursor)
    assert more == []


def test_record_count_skips_blank_lines(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.append("events", {"id": "1"})
    store.append("events", {"id": "2"})
    store.events_path.write_text(store.events_path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    assert store.record_count("events") == 2


def test_incomplete_last_line_is_not_consumed(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.events_path.write_text('{"id":"1"}\n{"id":"partial"', encoding="utf-8")
    items, cursor = store.read_since("events", 0)
    assert [item["id"] for item in items] == ["1"]
    store.events_path.write_text('{"id":"1"}\n{"id":"2"}\n', encoding="utf-8")
    items, _ = store.read_since("events", cursor)
    assert [item["id"] for item in items] == ["2"]


def test_query_records_paginates_newest_first(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    for index in range(5):
        store.append("events", {"id": str(index), "type": "created", "ts": f"2026-01-01T00:00:0{index}Z"})
    first = store.query_records("events", page=1, page_size=2)
    assert [item["id"] for item in first["items"]] == ["4", "3"]
    assert first["total"] == 5
    assert first["pages"] == 3
    assert first["page"] == 1
    last = store.query_records("events", page=3, page_size=2)
    assert [item["id"] for item in last["items"]] == ["0"]
    clamped = store.query_records("events", page=9, page_size=2)
    assert clamped["page"] == 3


def test_query_records_filters_time_and_type(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.append("events", {"id": "a", "type": "created", "ts": "2026-09-17T10:00:00Z"})
    store.append("events", {"id": "b", "type": "modified", "ts": "2026-09-17T11:00:00Z"})
    store.append("events", {"id": "c", "type": "created", "ts": "2026-09-17T12:00:00Z"})
    result = store.query_records(
        "events",
        page=1,
        page_size=100,
        ts_from="2026-09-17T18:30:00+08:00",
        ts_to="2026-09-17T20:00:59+08:00",
        event_type="created",
    )
    assert [item["id"] for item in result["items"]] == ["c"]
    assert result["total"] == 1
