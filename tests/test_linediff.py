from __future__ import annotations

from pathlib import Path

from filewatch.linediff import (
    MAX_CHANGE_ROWS,
    MAX_FILE_BYTES,
    MAX_LINE_CHARS,
    build_line_changes,
    content_fingerprint,
    is_noop_text_modified,
    load_line_changes_map,
    merge_line_changes,
    put_line_changes,
    read_text_file,
    settle_line_changes,
    snapshot_fingerprint,
)


def test_build_line_changes_add_del_replace() -> None:
    payload = build_line_changes("a\nb\nc\n", "a\nB\nc\nd\n", encoding="utf-8")
    assert payload["kind"] == "text"
    assert payload["encoding"] == "utf-8"
    assert payload["removed"] == 1
    assert payload["added"] == 2
    ops = [(row["op"], row["line"], row["text"]) for row in payload["changes"]]
    assert ("del", 2, "b") in ops
    assert ("add", 2, "B") in ops
    assert ("add", 4, "d") in ops


def test_build_line_changes_truncates_rows_and_line_text() -> None:
    old = "\n".join(f"old{i}" for i in range(MAX_CHANGE_ROWS + 20))
    new = "\n".join(f"new{i}" + ("x" * MAX_LINE_CHARS) for i in range(MAX_CHANGE_ROWS + 20))
    payload = build_line_changes(old, new)
    assert payload["truncated"] is True
    assert len(payload["changes"]) == MAX_CHANGE_ROWS
    assert payload["added"] > MAX_CHANGE_ROWS
    assert all(len(row["text"]) <= MAX_LINE_CHARS for row in payload["changes"])


def test_read_text_file_skips_binary_and_large(tmp_path: Path) -> None:
    binary = tmp_path / "bin.dat"
    binary.write_bytes(b"hello\x00world")
    skipped, text, encoding = read_text_file(binary)
    assert skipped == {"kind": "skipped", "reason": "binary"}
    assert text is None and encoding is None

    huge = tmp_path / "huge.txt"
    huge.write_bytes(b"a" * (MAX_FILE_BYTES + 1))
    skipped, _, _ = read_text_file(huge)
    assert skipped == {"kind": "skipped", "reason": "too_large"}

    modest = tmp_path / "modest.txt"
    modest.write_bytes(b"a" * 50)
    skipped, text, _ = read_text_file(modest, max_bytes=40)
    assert skipped == {"kind": "skipped", "reason": "too_large"}
    skipped, text, _ = read_text_file(modest, max_bytes=50)
    assert skipped is None
    assert text == "a" * 50


def test_settle_created_modified_deleted(tmp_path: Path) -> None:
    snaps = tmp_path / "snaps"
    target = tmp_path / "note.txt"
    target.write_text("one\n", encoding="utf-8")
    created = settle_line_changes(
        snaps, event_type="created", path=str(target), old_path=None, is_dir=False
    )
    assert created is not None
    assert created["kind"] == "text"
    assert created["added"] == 1
    assert created["removed"] == 0

    target.write_text("one\ntwo\n", encoding="utf-8")
    modified = settle_line_changes(
        snaps, event_type="modified", path=str(target), old_path=None, is_dir=False
    )
    assert modified is not None
    assert modified["added"] == 1
    assert modified["removed"] == 0
    assert any(row["op"] == "add" and row["text"] == "two" for row in modified["changes"])

    target.unlink()
    deleted = settle_line_changes(
        snaps, event_type="deleted", path=str(target), old_path=None, is_dir=False
    )
    assert deleted is not None
    assert deleted["removed"] == 2
    assert deleted["added"] == 0


def test_settle_modified_without_baseline(tmp_path: Path) -> None:
    snaps = tmp_path / "snaps"
    target = tmp_path / "late.txt"
    target.write_text("hello\n", encoding="utf-8")
    first = settle_line_changes(
        snaps, event_type="modified", path=str(target), old_path=None, is_dir=False
    )
    assert first == {"kind": "skipped", "reason": "no_baseline"}
    target.write_text("hello\nworld\n", encoding="utf-8")
    second = settle_line_changes(
        snaps, event_type="modified", path=str(target), old_path=None, is_dir=False
    )
    assert second is not None
    assert second["kind"] == "text"
    assert second["added"] == 1


def test_settle_dir_omits(tmp_path: Path) -> None:
    snaps = tmp_path / "snaps"
    folder = tmp_path / "dir"
    folder.mkdir()
    assert (
        settle_line_changes(snaps, event_type="created", path=str(folder), old_path=None, is_dir=True)
        is None
    )


def test_content_fingerprint_and_noop_modified(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("hello\n", encoding="utf-8")
    first = content_fingerprint(target)
    assert first is not None and first.startswith("t:")
    assert content_fingerprint(target) == first
    target.write_text("hello\nworld\n", encoding="utf-8")
    assert content_fingerprint(target) != first

    snaps = tmp_path / "snaps"
    settle_line_changes(snaps, event_type="created", path=str(target), old_path=None, is_dir=False)
    assert snapshot_fingerprint(snaps, target) == content_fingerprint(target)

    assert is_noop_text_modified(
        {"type": "modified", "line_changes": {"kind": "text", "added": 0, "removed": 0}}
    )
    assert not is_noop_text_modified(
        {"type": "created", "line_changes": {"kind": "text", "added": 0, "removed": 0}}
    )
    assert not is_noop_text_modified(
        {"type": "modified", "line_changes": {"kind": "text", "added": 1, "removed": 0}}
    )


def test_sidecar_merge(tmp_path: Path) -> None:
    path = tmp_path / "line_changes.json"
    put_line_changes(path, "evt_abc", {"kind": "text", "added": 1, "removed": 0, "changes": []})
    data = load_line_changes_map(path)
    assert "evt_abc" in data
    merged = merge_line_changes({"id": "evt_abc", "type": "modified"}, data)
    assert merged["line_changes"]["added"] == 1
    untouched = merge_line_changes({"id": "evt_other", "type": "modified"}, data)
    assert "line_changes" not in untouched
