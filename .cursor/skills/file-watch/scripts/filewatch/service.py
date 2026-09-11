from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from filewatch.config import Config, ConfigError, config_from_path, config_to_dict, parse_config_dict, summarize_config
from filewatch.models import STREAMS
from filewatch.nl_rules import merge_rules, rules_from_text
from filewatch.paths import sanitize_id, state_root
from filewatch.process import pid_alive, spawn_detached, terminate_pid
from filewatch.store import WatchStore, list_stores


def scripts_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def store_for(watch_id: str) -> WatchStore:
    return WatchStore(sanitize_id(watch_id))


def running_pid(store: WatchStore) -> tuple[bool, int | None]:
    pid = store.read_pid()
    if pid and pid_alive(pid):
        return True, pid
    return False, pid


def load_saved_config(store: WatchStore) -> Config | None:
    if not store.config_path.exists():
        return None
    raw = json.loads(store.config_path.read_text(encoding="utf-8"))
    return parse_config_dict(raw, source=str(store.config_path))


def describe_watcher(store: WatchStore) -> dict[str, Any]:
    running, pid = running_pid(store)
    config = None
    try:
        config = load_saved_config(store)
    except (ConfigError, json.JSONDecodeError, OSError):
        config = None
    watch_path = config.watch.path if config else None
    title = Path(watch_path).name if watch_path else store.watch_id
    last_event = None
    event_count = 0
    if store.events_path.exists():
        event_count = store.record_count("events")
        tail, _ = store.read_tail("events", limit=1)
        if tail:
            last_event = tail[-1]
    return {
        "watch_id": store.watch_id,
        "title": title,
        "running": running,
        "pid": pid,
        "path": watch_path,
        "recursive": config.watch.recursive if config else None,
        "rules": [rule.name for rule in config.rules] if config else [],
        "rule_count": len(config.rules) if config else 0,
        "event_count": event_count,
        "last_event": last_event,
        "pending_events": store.pending_count("events") if store.events_path.exists() else 0,
        "pending_jobs": store.pending_count("jobs") if store.jobs_path.exists() else 0,
        "cursors": store.read_cursors() if store.cursors_path.exists() else {},
        "home": str(store.dir),
    }


def list_watcher_payloads() -> list[dict[str, Any]]:
    return [describe_watcher(store) for store in list_stores()]


def find_watcher_by_path(path: str | Path) -> WatchStore | None:
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return None
    for store in list_stores():
        config = None
        try:
            config = load_saved_config(store)
        except (ConfigError, json.JSONDecodeError, OSError):
            continue
        if config is None:
            continue
        try:
            if Path(config.watch.path).resolve() == resolved:
                return store
        except OSError:
            continue
    return None


def spawn_daemon(store: WatchStore) -> int:
    env = os.environ.copy()
    env["FILEWATCH_HOME"] = str(state_root())
    scripts = scripts_dir()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(scripts), env.get("PYTHONPATH", "")]))
    entry = scripts / "filewatch_cli.py"
    argv = [sys.executable, str(entry), "run", "--id", store.watch_id]
    return spawn_detached(argv, store.log_path, env=env)


def start_watch(config: Config, watch_id: str | None = None) -> dict[str, Any]:
    watch_id = sanitize_id(watch_id or config.name)
    watch_path = Path(config.watch.path)
    if not watch_path.is_dir():
        return {
            "ok": False,
            "error": "not_found",
            "message": f"监听路径不是目录：{watch_path}",
            "path": str(watch_path),
        }
    store = store_for(watch_id)
    store.ensure()
    running, pid = running_pid(store)
    if running:
        return {
            "ok": True,
            "already_running": True,
            "applied": False,
            "watch_id": watch_id,
            "pid": pid,
            "path": config.watch.path,
            "message": "监听已在运行，本次 start 未应用新配置；请先 validate 再 reload",
        }
    store.clear_reload()
    store.config_path.write_text(
        json.dumps(config_to_dict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    store.clear_stop()
    spawned = spawn_daemon(store)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        recorded = store.read_pid()
        if recorded and pid_alive(recorded):
            return {
                "ok": True,
                "already_running": False,
                "watch_id": watch_id,
                "pid": recorded,
                "path": config.watch.path,
                "home": str(state_root()),
            }
        time.sleep(0.1)
    log_tail = ""
    if store.log_path.exists():
        log_tail = store.log_path.read_text(encoding="utf-8")[-2000:]
    return {
        "ok": False,
        "error": "start_failed",
        "message": "守护进程未能就绪",
        "spawned_pid": spawned,
        "log": log_tail,
    }


def allocate_watch_id(resolved: Path, explicit: str | None = None) -> str:
    if explicit:
        return sanitize_id(explicit)
    base = sanitize_id(resolved.name or "watch")
    store = store_for(base)
    if not store.config_path.exists():
        return base
    saved = load_saved_config(store)
    try:
        if saved is not None and Path(saved.watch.path).resolve() == resolved:
            return base
    except OSError:
        pass
    digest = hashlib.sha1(str(resolved).encode("utf-8")).hexdigest()[:8]
    return sanitize_id(f"{base}-{digest}")


def start_path(path: str, *, watch_id: str | None = None, recursive: bool = True, reuse: bool = True) -> dict[str, Any]:
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError as exc:
        return {"ok": False, "error": "not_found", "message": f"无法解析路径：{exc}"}
    if reuse:
        existing = find_watcher_by_path(resolved)
        if existing is not None:
            running, pid = running_pid(existing)
            if running:
                info = describe_watcher(existing)
                info.update(
                    {
                        "ok": True,
                        "already_running": True,
                        "applied": False,
                        "pid": pid,
                        "message": "已复用该路径上正在运行的监听",
                    }
                )
                return info
            saved = load_saved_config(existing)
            if saved is not None:
                return start_watch(saved, existing.watch_id)
            return start_watch(
                config_from_path(str(resolved), name=existing.watch_id, recursive=recursive),
                existing.watch_id,
            )
    allocated = allocate_watch_id(resolved, watch_id)
    config = config_from_path(str(resolved), name=allocated, recursive=recursive)
    return start_watch(config, allocated)


def stop_watch(watch_id: str) -> dict[str, Any]:
    watch_id = sanitize_id(watch_id)
    store = store_for(watch_id)
    running, pid = running_pid(store)
    store.request_stop()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        running, pid = running_pid(store)
        if not running:
            break
        time.sleep(0.1)
    if running and pid:
        terminate_pid(pid)
        time.sleep(0.2)
        running, pid = running_pid(store)
    if store.pid_path.exists() and not running:
        store.pid_path.unlink()
    return {"ok": True, "watch_id": watch_id, "running": running, "pid": pid}


def read_stream(
    watch_id: str,
    stream: str,
    *,
    since: int | None = None,
    limit: int = 100,
    tail: bool = False,
) -> dict[str, Any]:
    if stream not in STREAMS:
        return {"ok": False, "error": "bad_stream", "message": f"stream 必须是 {STREAMS} 之一"}
    store = store_for(watch_id)
    if tail and since is None:
        items, cursor = store.read_tail(stream, limit=limit)
        since = 0
        timed_out = not items
    else:
        offset = 0 if since is None else since
        items, cursor = store.read_since(stream, offset, limit)
        timed_out = not items
        since = offset
    return {
        "ok": True,
        "watch_id": sanitize_id(watch_id),
        "stream": stream,
        "timed_out": timed_out,
        "since": since,
        "cursor": cursor,
        "count": len(items),
        "items": items,
        **describe_watcher(store),
    }


def _missing_watcher(watch_id: str) -> dict[str, Any]:
    return {"ok": False, "error": "not_found", "message": f"没有找到监听 {watch_id}"}


def watcher_config(watch_id: str) -> dict[str, Any]:
    watch_id = sanitize_id(watch_id)
    store = store_for(watch_id)
    if not store.config_path.exists():
        return _missing_watcher(watch_id)
    config = load_saved_config(store)
    if config is None:
        return {"ok": False, "error": "bad_config", "message": "配置无法读取"}
    return {
        "ok": True,
        **describe_watcher(store),
        "config": config_to_dict(config),
        "summary": summarize_config(config),
    }


def wait_reload(store: WatchStore, generation: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(timeout, 0.5)
    while time.monotonic() < deadline:
        status = store.read_reload_status()
        if status and status.get("generation") == generation:
            if status.get("ok"):
                return {
                    "ok": True,
                    "watch_id": store.watch_id,
                    "generation": generation,
                    "rules": status.get("rules") or [],
                    "warnings": status.get("warnings") or [],
                    "applied_summary": status.get("applied") or {},
                    **describe_watcher(store),
                }
            return {
                "ok": False,
                "error": str(status.get("error") or "reload_failed"),
                "message": str(status.get("message") or "热更新失败"),
                "watch_id": store.watch_id,
                "generation": generation,
            }
        still_running, _ = running_pid(store)
        if not still_running:
            return {
                "ok": False,
                "error": "daemon_exited",
                "message": "热更新期间守护进程已退出",
                "watch_id": store.watch_id,
            }
        time.sleep(0.1)
    return {
        "ok": False,
        "error": "reload_timeout",
        "message": "守护进程未在超时内应用配置",
        "watch_id": store.watch_id,
        "generation": generation,
    }


def save_rules(watch_id: str, rules_raw: Any, *, timeout: float = 8.0) -> dict[str, Any]:
    watch_id = sanitize_id(watch_id)
    store = store_for(watch_id)
    if not store.config_path.exists():
        return _missing_watcher(watch_id)
    saved = load_saved_config(store)
    if saved is None:
        return {"ok": False, "error": "bad_config", "message": "配置无法读取"}
    if not isinstance(rules_raw, list):
        return {"ok": False, "error": "bad_request", "message": "rules 必须是列表"}
    raw = config_to_dict(saved)
    raw["rules"] = rules_raw
    try:
        parsed = parse_config_dict(raw, source=saved.source)
    except ConfigError as exc:
        return {"ok": False, "error": "bad_config", "message": str(exc)}
    config = Config(
        name=saved.name,
        watch=saved.watch,
        rules=parsed.rules,
        max_parallel_jobs=saved.max_parallel_jobs,
        source=saved.source,
    )
    payload = config_to_dict(config)
    running, pid = running_pid(store)
    if not running:
        store.config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            **describe_watcher(store),
            "applied": True,
            "reloaded": False,
            "running": False,
            "pid": pid,
            "message": "规则已保存，监听未运行；下次 start 后生效",
            "config": payload,
            "summary": summarize_config(config),
        }
    generation = uuid.uuid4().hex
    store.request_reload(payload, generation)
    result = wait_reload(store, generation, timeout)
    if not result.get("ok"):
        return result
    latest = load_saved_config(store) or config
    result.update(
        {
            "applied": True,
            "reloaded": True,
            "running": True,
            "pid": pid,
            "message": "规则已热更新",
            "config": config_to_dict(latest),
            "summary": summarize_config(latest),
        }
    )
    return result


def preview_rules_from_text(watch_id: str, text: str, *, mode: str | None = None) -> dict[str, Any]:
    watch_id = sanitize_id(watch_id)
    store = store_for(watch_id)
    if not store.config_path.exists():
        return _missing_watcher(watch_id)
    saved = load_saved_config(store)
    if saved is None:
        return {"ok": False, "error": "bad_config", "message": "配置无法读取"}
    existing = config_to_dict(saved)["rules"]
    generated = rules_from_text(
        text,
        existing_names=[str(item.get("name")) for item in existing],
        mode=mode,
    )
    if not generated.get("ok"):
        return generated
    resolved_mode = str(generated.get("mode") or "append")
    merged = merge_rules(existing, generated["rules"], resolved_mode)
    try:
        parse_config_dict({**config_to_dict(saved), "rules": merged}, source=saved.source)
    except ConfigError as exc:
        return {"ok": False, "error": "bad_config", "message": str(exc)}
    return {
        "ok": True,
        **describe_watcher(store),
        "mode": resolved_mode,
        "rules": generated["rules"],
        "merged_rules": merged,
        "notes": generated.get("notes") or [],
        "warnings": generated.get("warnings") or [],
    }


def apply_rules_from_text(
    watch_id: str,
    text: str,
    *,
    mode: str | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    preview = preview_rules_from_text(watch_id, text, mode=mode)
    if not preview.get("ok"):
        return preview
    saved = save_rules(watch_id, preview["merged_rules"], timeout=timeout)
    if not saved.get("ok"):
        return saved
    saved.update(
        {
            "mode": preview["mode"],
            "generated": preview["rules"],
            "notes": preview["notes"],
            "warnings": preview["warnings"],
        }
    )
    return saved

