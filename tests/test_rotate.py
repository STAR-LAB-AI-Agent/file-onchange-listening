from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from filewatch.agent.logging import read_index, upsert_job
from filewatch.rotate import (
    CURSOR_EPOCH,
    CURSOR_SPAN,
    DailyFileStream,
    decode_cursor,
    encode_cursor,
    keep_days,
    prune_agent_logs,
)


def test_encode_decode_cursor_roundtrip() -> None:
    day = datetime(2026, 9, 19).date()
    cursor = encode_cursor(day, 1234)
    assert cursor == (day - CURSOR_EPOCH).days * CURSOR_SPAN + 1234
    assert decode_cursor(cursor) == (day, 1234)
    assert decode_cursor(0) == (CURSOR_EPOCH, 0)


def test_keep_days_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FILEWATCH_LOG_KEEP_DAYS", "3")
    assert keep_days() == 3
    monkeypatch.setenv("FILEWATCH_LOG_KEEP_DAYS", "0")
    assert keep_days() == 1
    monkeypatch.setenv("FILEWATCH_LOG_KEEP_DAYS", "9999")
    assert keep_days() == 365


def test_daily_file_stream_rolls(tmp_path: Path) -> None:
    cst = timezone(timedelta(hours=8))
    current = {"now": datetime(2026, 9, 18, 10, 0, tzinfo=cst)}
    stream = DailyFileStream(tmp_path, clock=lambda: current["now"], redirect_std=False)
    stream.write("day1\n")
    current["now"] = datetime(2026, 9, 19, 10, 0, tzinfo=cst)
    stream.write("day2\n")
    stream.close()
    assert (tmp_path / "daemon-2026-09-18.log").read_text(encoding="utf-8") == "day1\n"
    assert (tmp_path / "daemon-2026-09-19.log").read_text(encoding="utf-8") == "day2\n"


def test_prune_agent_logs_keeps_recent_and_running(tmp_path: Path) -> None:
    log_dir = tmp_path / "agent-logs"
    old = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    upsert_job(log_dir, {"job_id": "job_old", "ts": old, "ended_ts": old, "status": "ok"})
    (log_dir / "job_old.jsonl").write_text("{}\n", encoding="utf-8")
    upsert_job(log_dir, {"job_id": "job_new", "ts": now, "ended_ts": now, "status": "ok"})
    (log_dir / "job_new.jsonl").write_text("{}\n", encoding="utf-8")
    upsert_job(log_dir, {"job_id": "job_run", "ts": old, "status": "running"})
    (log_dir / "job_run.jsonl").write_text("{}\n", encoding="utf-8")
    prune_agent_logs(log_dir, keep=14)
    assert not (log_dir / "job_old.jsonl").exists()
    assert (log_dir / "job_new.jsonl").exists()
    assert (log_dir / "job_run.jsonl").exists()
    ids = {item["job_id"] for item in read_index(log_dir)["jobs"]}
    assert ids == {"job_new", "job_run"}
