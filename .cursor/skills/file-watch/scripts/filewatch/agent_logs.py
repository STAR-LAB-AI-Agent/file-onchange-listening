from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from filewatch.agent.logging import format_tool_command, format_tool_output, read_index

LOG_PAGE = 100


def agent_log_dir(store_dir: Path) -> Path:
    return store_dir / "agent-logs"


def normalize_log_event(
    raw: dict[str, Any],
    *,
    seq: int,
    job_id: str,
    session: int,
) -> dict[str, Any]:
    if raw.get("kind"):
        event = dict(raw)
        event.setdefault("seq", seq)
        event.setdefault("job_id", job_id)
        event["session"] = session
        return event
    tool = str(raw.get("tool") or "cmd")
    ok = bool(raw.get("ok", True))
    output = raw.get("output")
    output_text = format_tool_output(output)
    arguments = raw.get("input") if isinstance(raw.get("input"), dict) else {}
    command = format_tool_command(tool, arguments)
    message = ""
    if isinstance(output, dict):
        message = str(output.get("message") or output.get("error") or "")
    return {
        "kind": "cmd" if ok else "tool_exec_error",
        "seq": int(raw.get("seq") or seq),
        "session": session,
        "job_id": job_id,
        "ts": raw.get("ts"),
        "tool": tool,
        "tool_call_id": raw.get("tool_call_id"),
        "command": command,
        "output": output_text,
        "exit_code": 0 if ok else 1,
        "duration_ms": raw.get("duration_ms"),
        "ok": ok,
        "text": None if ok else (message or output_text),
    }


def _parse_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                events.append(raw)
    return events


def list_jobs(log_dir: Path) -> list[dict[str, Any]]:
    data = read_index(log_dir)
    indexed = [item for item in data.get("jobs", []) if isinstance(item, dict) and item.get("job_id")]
    by_id = {str(item["job_id"]): dict(item) for item in indexed}
    if log_dir.exists():
        for path in log_dir.glob("job_*.jsonl"):
            job_id = path.stem
            if job_id in by_id:
                continue
            by_id[job_id] = {
                "job_id": job_id,
                "status": "unknown",
                "ts": None,
            }
    jobs = list(by_id.values())
    jobs.sort(key=lambda item: (int(item.get("session") or 0), str(item.get("ts") or ""), str(item.get("job_id") or "")))
    for index, job in enumerate(jobs, start=1):
        if not int(job.get("session") or 0):
            job["session"] = index
    jobs.sort(key=lambda item: int(item.get("session") or 0))
    return jobs


def scoped_jobs(log_dir: Path, rule: str | None = None) -> list[dict[str, Any]]:
    jobs = list_jobs(log_dir)
    if rule is not None:
        jobs = [item for item in jobs if str(item.get("rule") or "") == rule]
    scoped: list[dict[str, Any]] = []
    for index, job in enumerate(jobs, start=1):
        item = dict(job)
        item["session"] = index
        scoped.append(item)
    return scoped


def resolve_job(jobs: list[dict[str, Any]], session: int | None) -> dict[str, Any] | None:
    if not jobs:
        return None
    if session is None:
        return jobs[-1]
    for job in jobs:
        if int(job.get("session") or 0) == session:
            return job
    return None


def summarize_runs(log_dir: Path) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for job in list_jobs(log_dir):
        name = str(job.get("rule") or "")
        grouped.setdefault(name, []).append(job)
    stats: list[dict[str, Any]] = []
    for name, items in grouped.items():
        last = items[-1]
        stats.append(
            {
                "rule": name,
                "run_count": len(items),
                "running": any(str(item.get("status") or "") == "running" for item in items),
                "last_status": last.get("status"),
                "last_ts": last.get("ended_ts") or last.get("ts"),
                "last_path": last.get("path"),
            }
        )
    stats.sort(key=lambda item: str(item.get("rule") or ""))
    return stats


def read_job_events(log_dir: Path, job: dict[str, Any]) -> list[dict[str, Any]]:
    job_id = str(job.get("job_id") or "")
    session = int(job.get("session") or 1)
    path = log_dir / f"{job_id}.jsonl"
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(_parse_jsonl(path), start=1):
        events.append(normalize_log_event(raw, seq=index, job_id=job_id, session=session))
    return events


def read_agent_logs(
    store_dir: Path,
    *,
    session: int | None = None,
    offset: int = 0,
    limit: int = LOG_PAGE,
    tail: bool = False,
    before: int | None = None,
    rule: str | None = None,
    summary: bool = False,
) -> dict[str, Any]:
    log_dir = agent_log_dir(store_dir)
    stats = summarize_runs(log_dir)
    if summary:
        return {"ok": True, "stats": stats, "events": [], "session": 1, "session_count": 0}
    jobs = scoped_jobs(log_dir, rule)
    job = resolve_job(jobs, session)
    session_count = len(jobs)
    if job is None:
        return {
            "ok": True,
            "events": [],
            "session": 1,
            "session_count": 0,
            "job": None,
            "running": False,
            "offset": max(0, offset),
            "oldest": 0,
            "has_older": False,
            "total": 0,
            "file_end": 0,
            "rule": rule,
            "stats": stats,
        }
    events = read_job_events(log_dir, job)
    total = len(events)
    file_end = (events[-1]["seq"] + 1) if events else 0
    current_session = int(job.get("session") or 1)
    if before is not None:
        filtered = [item for item in events if int(item.get("seq") or 0) < before]
        page = filtered[-max(1, limit) :]
    elif tail:
        page = events[-max(1, limit) :] if events else []
    else:
        start = max(0, offset)
        page = [item for item in events if int(item.get("seq") or 0) >= start][: max(1, limit)]
    oldest = int(page[0]["seq"]) if page else 0
    if before is not None:
        has_older = bool(page) and int(page[0]["seq"]) > 1
    elif tail:
        has_older = total > len(page)
    else:
        first_seq = int(page[0]["seq"]) if page else file_end
        has_older = first_seq > 1
    next_offset = (int(page[-1]["seq"]) + 1) if page else max(offset, file_end)
    return {
        "ok": True,
        "events": page,
        "session": current_session,
        "session_count": session_count,
        "job": job,
        "running": str(job.get("status") or "") == "running",
        "offset": next_offset,
        "oldest": oldest,
        "has_older": has_older,
        "total": total,
        "file_end": file_end,
        "rule": rule,
        "stats": stats,
    }
