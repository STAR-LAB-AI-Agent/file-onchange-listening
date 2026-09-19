from __future__ import annotations

import json
from pathlib import Path

from filewatch.agent.logging import ToolCallLogger, upsert_job
from filewatch.agent.types import ToolCallRecord, ToolResult
from filewatch.agent_logs import normalize_log_event, read_agent_logs


def test_normalize_legacy_tool_line() -> None:
    raw = {
        "ts": "2026-01-01T00:00:00Z",
        "tool": "Write",
        "tool_call_id": "c1",
        "ok": True,
        "input": {"path": "a.md", "content": "x"},
        "output": {"ok": True, "path": "a.md"},
        "duration_ms": 1.2,
    }
    event = normalize_log_event(raw, seq=3, job_id="job_1", session=2)
    assert event["kind"] == "cmd"
    assert event["seq"] == 3
    assert event["session"] == 2
    assert event["command"].startswith("Write")
    assert event["ok"] is True


def test_read_agent_logs_tail_and_before(tmp_path: Path) -> None:
    log_dir = tmp_path / "agent-logs"
    logger = ToolCallLogger(log_dir / "job_a.jsonl", job_id="job_a", meta={"rule": "md"})
    for index in range(5):
        logger.emit("agent", text=f"step {index}")
    logger.close("ok", "已完成，共 1 步 · 工具 0 次")

    page = read_agent_logs(tmp_path, tail=True, limit=3)
    assert page["ok"] is True
    assert page["session"] == 1
    assert page["session_count"] == 1
    assert page["running"] is False
    assert len(page["events"]) == 3
    assert page["has_older"] is True
    texts = [item.get("text") for item in page["events"]]
    assert texts[-1] == "已完成，共 1 步 · 工具 0 次"
    assert "step 4" in texts

    older = read_agent_logs(tmp_path, before=page["oldest"], limit=10)
    assert [item.get("text") for item in older["events"] if item.get("kind") == "agent"] == [
        "step 0",
        "step 1",
        "step 2",
    ]


def test_read_agent_logs_two_sessions(tmp_path: Path) -> None:
    log_dir = tmp_path / "agent-logs"
    first = ToolCallLogger(log_dir / "job_one.jsonl", job_id="job_one")
    first.emit("system", text="first")
    first.close("ok", "done")
    second = ToolCallLogger(log_dir / "job_two.jsonl", job_id="job_two")
    second.emit("system", text="second")
    second.close("error", "失败")

    latest = read_agent_logs(tmp_path, tail=True)
    assert latest["session"] == 2
    assert latest["session_count"] == 2
    assert latest["job"]["job_id"] == "job_two"
    assert any(item.get("text") == "second" for item in latest["events"])

    hist = read_agent_logs(tmp_path, session=1, tail=True)
    assert hist["session"] == 1
    assert hist["job"]["job_id"] == "job_one"


def test_logger_writes_tool_cmd(tmp_path: Path) -> None:
    log_dir = tmp_path / "agent-logs"
    logger = ToolCallLogger(log_dir / "job_t.jsonl", job_id="job_t")
    logger.log(
        ToolCallRecord(
            id="c1",
            name="Glob",
            arguments={"pattern": "**/*.md"},
            result=ToolResult(ok=True, data={"matches": ["a.md"]}),
            duration_ms=2.0,
        )
    )
    logger.close("ok", "done")
    page = read_agent_logs(tmp_path, tail=True)
    kinds = [item["kind"] for item in page["events"]]
    assert "cmd" in kinds
    cmd = next(item for item in page["events"] if item["kind"] == "cmd")
    assert cmd["tool"] == "Glob"
    assert "a.md" in (cmd.get("output") or "")


def test_read_agent_logs_filters_by_rule(tmp_path: Path) -> None:
    log_dir = tmp_path / "agent-logs"
    first = ToolCallLogger(log_dir / "job_md.jsonl", job_id="job_md", meta={"rule": "md"})
    first.emit("agent", text="md-run")
    first.close("ok", "done")
    second = ToolCallLogger(log_dir / "job_txt.jsonl", job_id="job_txt", meta={"rule": "txt"})
    second.emit("agent", text="txt-run")
    second.close("ok", "done")
    third = ToolCallLogger(log_dir / "job_md2.jsonl", job_id="job_md2", meta={"rule": "md"})
    third.emit("agent", text="md-run-2")
    third.close("ok", "done")

    md = read_agent_logs(tmp_path, rule="md", tail=True)
    assert md["session_count"] == 2
    assert md["session"] == 2
    assert md["job"]["job_id"] == "job_md2"
    assert any(item.get("text") == "md-run-2" for item in md["events"])
    assert all(item.get("session") == 2 for item in md["events"])

    hist = read_agent_logs(tmp_path, rule="md", session=1, tail=True)
    assert hist["job"]["job_id"] == "job_md"
    assert hist["session"] == 1

    summary = read_agent_logs(tmp_path, summary=True)
    by_rule = {item["rule"]: item for item in summary["stats"]}
    assert by_rule["md"]["run_count"] == 2
    assert by_rule["txt"]["run_count"] == 1


def test_upsert_job_assigns_session(tmp_path: Path) -> None:
    first = upsert_job(tmp_path, {"job_id": "a", "status": "running"})
    second = upsert_job(tmp_path, {"job_id": "b", "status": "running"})
    assert first["session"] == 1
    assert second["session"] == 2
    again = upsert_job(tmp_path, {"job_id": "a", "status": "ok"})
    assert again["session"] == 1
    assert again["status"] == "ok"
