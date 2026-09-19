from __future__ import annotations

from datetime import datetime, timedelta, timezone

from filewatch.linediff import put_line_changes
from filewatch.rotate import stream_file
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


def test_read_skips_invalid_jsonl_lines(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.events_path.write_text('{"id":"ok"}\nnot-json\n{"id":"also"}\n', encoding="utf-8")
    items, _ = store.read_since("events", 0)
    assert [item["id"] for item in items] == ["ok", "also"]
    queried = store.query_records("events", page=1, page_size=10)
    assert [item["id"] for item in queried["items"]] == ["also", "ok"]


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


def test_query_records_filters_path_query(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.append(
        "events",
        {"id": "keep", "type": "created", "path": r"D:\data\inbox\README.md", "ts": "2026-09-17T10:00:00Z"},
    )
    store.append(
        "events",
        {"id": "moved", "type": "moved", "path": r"D:\data\inbox\docs\note.txt", "old_path": r"D:\data\inbox\draft.md", "ts": "2026-09-17T11:00:00Z"},
    )
    store.append(
        "events",
        {"id": "other", "type": "modified", "path": r"D:\data\inbox\skip.log", "ts": "2026-09-17T12:00:00Z"},
    )
    by_name = store.query_records("events", page=1, page_size=100, path_query="readme.md")
    assert [item["id"] for item in by_name["items"]] == ["keep"]
    by_slash = store.query_records("events", page=1, page_size=100, path_query="inbox/docs")
    assert [item["id"] for item in by_slash["items"]] == ["moved"]
    by_old = store.query_records("events", page=1, page_size=100, path_query="DRAFT.MD")
    assert [item["id"] for item in by_old["items"]] == ["moved"]
    empty = store.query_records("events", page=1, page_size=100, path_query="   ")
    assert [item["id"] for item in empty["items"]] == ["other", "moved", "keep"]


def test_ack_cannot_move_backwards(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.append("jobs", {"id": "1"})
    items, cursor, _ = store.wait("jobs", 0, timeout=0.1, limit=10)
    assert items
    store.ack("jobs", cursor)
    try:
        store.ack("jobs", 0)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "backwards" in str(exc)


def test_query_records_replaces_superseded_pending_modified(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.append(
        "events",
        {
            "id": "old",
            "type": "modified",
            "path": r"D:\data\inbox\a.txt",
            "ts": "2026-09-17T10:00:00Z",
            "line_changes": {"kind": "pending"},
        },
    )
    store.append(
        "events",
        {
            "id": "latest",
            "type": "modified",
            "path": r"D:\data\inbox\a.txt",
            "ts": "2026-09-17T10:00:01Z",
            "line_changes": {"kind": "pending"},
        },
    )
    store.append(
        "events",
        {
            "id": "other",
            "type": "modified",
            "path": r"D:\data\inbox\b.txt",
            "ts": "2026-09-17T10:00:02Z",
            "line_changes": {"kind": "pending"},
        },
    )
    pending = store.query_records("events", page=1, page_size=100)
    assert [item["id"] for item in pending["items"]] == ["other", "latest"]

    put_line_changes(
        store.line_changes_path,
        "latest",
        {"kind": "text", "added": 2, "removed": 1, "truncated": False, "changes": []},
    )
    settled = store.query_records("events", page=1, page_size=100)
    assert [item["id"] for item in settled["items"]] == ["other", "latest"]
    assert settled["items"][1]["line_changes"]["added"] == 2


def test_query_records_hides_noop_modified(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    store.append("events", {"id": "keep", "type": "created", "ts": "2026-09-17T10:00:00Z"})
    store.append(
        "events",
        {"id": "noop", "type": "modified", "ts": "2026-09-17T11:00:00Z"},
    )
    put_line_changes(
        store.line_changes_path,
        "noop",
        {"kind": "text", "added": 0, "removed": 0, "truncated": False, "changes": []},
    )
    result = store.query_records("events", page=1, page_size=100)
    assert [item["id"] for item in result["items"]] == ["keep"]
    assert result["total"] == 1


def test_query_records_rejects_bad_time(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.ensure()
    try:
        store.query_records("events", ts_from="not-a-date")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert str(exc) == "ts_from"


CST = timezone(timedelta(hours=8))


def test_append_writes_dated_file(tmp_path) -> None:
    now = datetime(2026, 9, 18, 15, 0, tzinfo=CST)
    store = WatchStore("demo", root=tmp_path, clock=lambda: now)
    store.append("events", {"id": "a"})
    dated = stream_file(store.dir, "events", now.date())
    assert dated.exists()
    assert not (store.dir / "events.jsonl").exists()
    assert '"id": "a"' in dated.read_text(encoding="utf-8")


def test_read_since_crosses_midnight(tmp_path) -> None:
    current = {"now": datetime(2026, 9, 18, 23, 0, tzinfo=CST)}
    store = WatchStore("demo", root=tmp_path, clock=lambda: current["now"])
    store.append("events", {"id": "old"})
    items, cursor, _ = store.wait("events", 0, timeout=0.1, limit=10)
    assert [item["id"] for item in items] == ["old"]
    current["now"] = datetime(2026, 9, 19, 1, 0, tzinfo=CST)
    store.append("events", {"id": "new"})
    more, _ = store.read_since("events", cursor)
    assert [item["id"] for item in more] == ["new"]
    all_items, _ = store.read_since("events", 0)
    assert [item["id"] for item in all_items] == ["old", "new"]


def test_prune_rotated_drops_old_days(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_LOG_KEEP_DAYS", "2")
    current = {"now": datetime(2026, 9, 1, 10, 0, tzinfo=CST)}
    store = WatchStore("demo", root=tmp_path, clock=lambda: current["now"])
    store.append("events", {"id": "ancient"})
    put_line_changes(store.line_changes_path, "ancient", {"kind": "text", "added": 1, "removed": 0})
    current["now"] = datetime(2026, 9, 19, 10, 0, tzinfo=CST)
    store.append("events", {"id": "today"})
    put_line_changes(store.line_changes_path, "today", {"kind": "text", "added": 2, "removed": 0})
    store.prune_rotated()
    ids = [item["id"] for item in store.read_since("events", 0)[0]]
    assert ids == ["today"]
    sidecar = store.line_changes_path.read_text(encoding="utf-8")
    assert "ancient" not in sidecar
    assert "today" in sidecar


def test_migrate_legacy_events_and_cursor(tmp_path) -> None:
    store = WatchStore("demo", root=tmp_path)
    store.dir.mkdir(parents=True)
    legacy = store.dir / "events.jsonl"
    line = '{"id":"legacy"}\n'
    legacy.write_text(line, encoding="utf-8")
    store.write_cursors({"events": len(line), "jobs": 0})
    store.ensure()
    assert not legacy.exists()
    leftover, _ = store.read_since("events", store.read_cursors()["events"])
    assert leftover == []
    items, _ = store.read_since("events", 0)
    assert [item["id"] for item in items] == ["legacy"]
