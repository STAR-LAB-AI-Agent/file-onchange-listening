from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from filewatch.agent_logs import read_agent_logs
from filewatch.llm import list_llm_models, test_llm_connection
from filewatch.models import DEFAULT_DEBOUNCE_MS, DEFAULT_LINE_DIFF_MAX_BYTES, DEFAULT_LINE_DIFF_QUIET_MS, EVENT_TYPES
from filewatch.paths import state_root
from filewatch.process import claim_listen_port, pid_alive, terminate_pid
from filewatch.service import (
    apply_edit_rule_from_text,
    apply_rules_from_text,
    apply_watch_timing,
    describe_watcher,
    exclude_frequent_paths,
    list_watcher_payloads,
    preview_edit_rule_from_text,
    preview_rules_from_text,
    prune_rotated_logs,
    read_stream,
    rename_watcher,
    save_rules,
    save_watch_options,
    start_path,
    stop_watch,
    store_for,
    watcher_config,
)
from filewatch.settings import probe_dingtalk_from_request, public_settings, save_settings

log = logging.getLogger("filewatch.web")

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")

WEBUI_DIR = Path(__file__).resolve().parent / "webui"
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class WatchWebHandler(BaseHTTPRequestHandler):
    server_version = "filewatch-web/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        line = fmt % args if args else fmt
        if " /api/" in f" {line}" and ("/events" in line or "/agent-logs" in line):
            return
        log.info("%s - %s", self.address_string(), line)

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:
            log.exception("request failed: %s", getattr(self, "path", ""))
            try:
                self._json(500, {"ok": False, "error": "internal", "message": "服务处理请求时出错"})
            except Exception:
                return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        if path in {"/", "/index.html"}:
            self._send_file(WEBUI_DIR / "index.html", "text/html; charset=utf-8")
            return
        if not path.startswith("/api/"):
            static_file = _safe_webui_file(path)
            if static_file is not None:
                self._send_file(static_file)
                return
            if "." not in Path(path).name:
                self._send_file(WEBUI_DIR / "index.html", "text/html; charset=utf-8")
                return
            self._json(404, {"ok": False, "error": "not_found", "message": "未知路径"})
            return
        if path == "/api/health":
            self._json(200, {"ok": True, "service": "filewatch-web"})
            return
        if path == "/api/settings":
            self._json(200, public_settings())
            return
        if path == "/api/watchers":
            self._json(200, {"ok": True, "watchers": list_watcher_payloads()})
            return
        watch_id = _match_watch_id(r"/api/watchers/([^/]+)/config", path)
        if watch_id is not None:
            if watch_id is False:
                self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
                return
            payload = watcher_config(watch_id)
            self._json(200 if payload.get("ok") else 404, payload)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)", path)
        if match:
            watch_id = match.group(1)
            if not ID_RE.fullmatch(watch_id):
                self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
                return
            store = store_for(watch_id)
            if not store.config_path.exists() and not store.has_records("events"):
                self._json(404, {"ok": False, "error": "not_found", "message": f"没有找到监听 {watch_id}"})
                return
            self._json(200, {"ok": True, **describe_watcher(store)})
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/events", path)
        if match:
            watch_id = match.group(1)
            if not ID_RE.fullmatch(watch_id):
                self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
                return
            store = store_for(watch_id)
            if not store.config_path.exists() and not store.has_records("events"):
                self._json(404, {"ok": False, "error": "not_found", "message": f"没有找到监听 {watch_id}"})
                return
            since = _int_arg(query, "since")
            limit = _int_arg(query, "limit", 100) or 100
            limit = max(1, min(limit, 500))
            tail = _bool_arg(query, "tail")
            page = _int_arg(query, "page")
            page_size = _int_arg(query, "page_size", 100) or 100
            ts_from = _str_arg(query, "ts_from")
            ts_to = _str_arg(query, "ts_to")
            event_type = _str_arg(query, "type")
            path_query = _str_arg(query, "q")
            include_frequent = _bool_arg(query, "frequent")
            if event_type == "all":
                event_type = None
            if event_type and event_type not in EVENT_TYPES:
                self._json(400, {"ok": False, "error": "bad_request", "message": "type 无效"})
                return
            payload = read_stream(
                watch_id,
                "events",
                since=since,
                limit=limit,
                tail=tail,
                page=page,
                page_size=page_size,
                ts_from=ts_from,
                ts_to=ts_to,
                event_type=event_type,
                path_query=path_query,
                include_frequent=include_frequent,
            )
            self._json(200 if payload.get("ok") else 400, payload)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/agent-logs/stream", path)
        if match:
            self._stream_agent_logs(match.group(1), query)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/agent-logs", path)
        if match:
            self._get_agent_logs(match.group(1), query)
            return
        self._json(404, {"ok": False, "error": "not_found", "message": "未知路径"})

    def do_PATCH(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        body = self._read_json_body()
        if isinstance(body, dict) and body.get("ok") is False and body.get("error") == "bad_json":
            self._json(400, body)
            return
        data = body if isinstance(body, dict) else {}
        match = re.fullmatch(r"/api/watchers/([^/]+)", path)
        if match:
            self._handle_rename(match.group(1), data)
            return
        self._json(404, {"ok": False, "error": "not_found", "message": "未知路径"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        body = self._read_json_body()
        if isinstance(body, dict) and body.get("ok") is False and body.get("error") == "bad_json":
            self._json(400, body)
            return
        data = body if isinstance(body, dict) else {}
        if path == "/api/settings/test":
            payload = test_llm_connection()
            self._json(200 if payload.get("ok") else 400, payload)
            return
        if path == "/api/settings/models":
            payload = list_llm_models(data)
            self._json(200 if payload.get("ok") else 400, payload)
            return
        if path == "/api/settings/dingtalk/test":
            payload = probe_dingtalk_from_request(data)
            self._json(200 if payload.get("ok") else 400, payload)
            return
        if path == "/api/watchers/start":
            folder = data.get("path")
            if not folder or not isinstance(folder, str):
                self._json(400, {"ok": False, "error": "bad_request", "message": "必须提供 path"})
                return
            watch_id = data.get("id")
            if watch_id is not None and not isinstance(watch_id, str):
                self._json(400, {"ok": False, "error": "bad_request", "message": "id 必须是字符串"})
                return
            name = data.get("name")
            if name is not None and not isinstance(name, str):
                self._json(400, {"ok": False, "error": "bad_request", "message": "name 必须是字符串"})
                return
            recursive = data.get("recursive", True)
            if not isinstance(recursive, bool):
                self._json(400, {"ok": False, "error": "bad_request", "message": "recursive 必须是布尔值"})
                return
            record_all = data.get("record_all", True)
            if not isinstance(record_all, bool):
                self._json(400, {"ok": False, "error": "bad_request", "message": "record_all 必须是布尔值"})
                return
            payload = start_path(
                folder,
                watch_id=watch_id,
                name=name,
                recursive=recursive,
                record_all=record_all,
                reuse=True,
            )
            code = 200 if payload.get("ok") else 400
            if payload.get("error") == "not_found":
                code = 404
            elif payload.get("error") == "start_failed":
                code = 500
            self._json(code, payload)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/stop", path)
        if match:
            watch_id = match.group(1)
            if not ID_RE.fullmatch(watch_id):
                self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
                return
            self._json(200, stop_watch(watch_id))
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/rules/(\d+)/from-text", path)
        if match:
            self._handle_edit_rule_from_text(match.group(1), int(match.group(2)), data)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/rules/from-text", path)
        if match:
            self._handle_rules_from_text(match.group(1), data)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/rules", path)
        if match:
            self._handle_save_rules(match.group(1), data)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/exclude-paths", path)
        if match:
            self._handle_exclude_paths(match.group(1), data)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/rename", path)
        if match:
            self._handle_rename(match.group(1), data)
            return
        self._json(404, {"ok": False, "error": "not_found", "message": "未知路径"})

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        body = self._read_json_body()
        if isinstance(body, dict) and body.get("ok") is False and body.get("error") == "bad_json":
            self._json(400, body)
            return
        data = body if isinstance(body, dict) else {}
        if path == "/api/settings":
            payload = save_settings(data)
            if payload.get("ok") and isinstance(data.get("watch"), dict):
                timing = payload.get("watch") or {}
                applied = apply_watch_timing(
                    int(timing.get("debounce_ms", DEFAULT_DEBOUNCE_MS)),
                    int(timing.get("line_diff_quiet_ms", DEFAULT_LINE_DIFF_QUIET_MS)),
                    int(timing.get("line_diff_max_bytes", DEFAULT_LINE_DIFF_MAX_BYTES)),
                )
                payload["applied_watchers"] = applied.get("watchers") or []
            if payload.get("ok") and isinstance(data.get("logs"), dict):
                pruned = prune_rotated_logs()
                payload["pruned_watchers"] = pruned.get("watchers") or []
            self._json(200 if payload.get("ok") else 400, payload)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/watch", path)
        if match:
            self._handle_save_watch(match.group(1), data)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/rules", path)
        if match:
            self._handle_save_rules(match.group(1), data)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)", path)
        if match:
            self._handle_rename(match.group(1), data)
            return
        self._json(404, {"ok": False, "error": "not_found", "message": "未知路径"})

    def _watcher_store(self, watch_id: str):
        if not ID_RE.fullmatch(watch_id):
            self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
            return None
        store = store_for(watch_id)
        if not store.config_path.exists() and not store.has_records("events"):
            self._json(404, {"ok": False, "error": "not_found", "message": f"没有找到监听 {watch_id}"})
            return None
        return store

    def _get_agent_logs(self, watch_id: str, query: dict[str, list[str]]) -> None:
        store = self._watcher_store(watch_id)
        if store is None:
            return
        session = _int_arg(query, "session")
        offset = _int_arg(query, "from_offset", 0) or 0
        limit = _int_arg(query, "limit", 100) or 100
        limit = max(1, min(limit, 500))
        tail = _bool_arg(query, "tail")
        before = _int_arg(query, "before")
        rule = _str_arg(query, "rule")
        payload = read_agent_logs(
            store.dir,
            session=session,
            offset=offset,
            limit=limit,
            tail=tail,
            before=before,
            rule=rule,
            summary=_bool_arg(query, "summary"),
        )
        payload["watch_id"] = store.watch_id
        self._json(200, payload)

    def _stream_agent_logs(self, watch_id: str, query: dict[str, list[str]]) -> None:
        store = self._watcher_store(watch_id)
        if store is None:
            return
        session = _int_arg(query, "session")
        rule = _str_arg(query, "rule")
        offset = max(0, _int_arg(query, "from_offset", 0) or 0)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 800\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return
        last_status: tuple[Any, ...] | None = None
        last_session: int | None = None
        follow_latest = session is None
        while True:
            page = read_agent_logs(
                store.dir,
                session=session,
                offset=offset,
                limit=200,
                rule=rule,
            )
            current_session = int(page.get("session") or 1)
            if follow_latest and last_session is not None and current_session != last_session:
                offset = 0
                page = read_agent_logs(store.dir, session=None, offset=0, limit=200, rule=rule)
                current_session = int(page.get("session") or 1)
            last_session = current_session
            for event in page.get("events") or []:
                if not self._sse({"type": "event", **event}):
                    return
            if page.get("events"):
                offset = int(page.get("offset") or offset)
            else:
                offset = max(offset, int(page.get("file_end") or 0))
            status = (
                bool(page.get("running")),
                current_session,
                int(page.get("session_count") or 0),
            )
            if status != last_status:
                last_status = status
                if not self._sse(
                    {
                        "type": "status",
                        "running": status[0],
                        "session": status[1],
                        "session_count": status[2],
                    }
                ):
                    return
            time.sleep(0.4)

    def _sse(self, payload: dict[str, Any]) -> bool:
        body = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False
        return True

    def _handle_save_rules(self, watch_id: str, data: dict[str, Any]) -> None:
        if not ID_RE.fullmatch(watch_id):
            self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
            return
        payload = save_rules(watch_id, data.get("rules"))
        code = 200 if payload.get("ok") else 400
        if payload.get("error") == "not_found":
            code = 404
        self._json(code, payload)

    def _handle_exclude_paths(self, watch_id: str, data: dict[str, Any]) -> None:
        if not ID_RE.fullmatch(watch_id):
            self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
            return
        payload = exclude_frequent_paths(watch_id, data.get("paths"))
        code = 200 if payload.get("ok") else 400
        if payload.get("error") == "not_found":
            code = 404
        self._json(code, payload)

    def _handle_save_watch(self, watch_id: str, data: dict[str, Any]) -> None:
        if not ID_RE.fullmatch(watch_id):
            self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
            return
        if "record_all" not in data:
            self._json(400, {"ok": False, "error": "bad_request", "message": "必须提供 record_all"})
            return
        record_all = data.get("record_all")
        if not isinstance(record_all, bool):
            self._json(400, {"ok": False, "error": "bad_request", "message": "record_all 必须是布尔值"})
            return
        payload = save_watch_options(watch_id, record_all=record_all)
        code = 200 if payload.get("ok") else 400
        if payload.get("error") == "not_found":
            code = 404
        self._json(code, payload)

    def _handle_rename(self, watch_id: str, data: dict[str, Any]) -> None:
        if not ID_RE.fullmatch(watch_id):
            self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
            return
        name = data.get("name", data.get("title"))
        if name is None:
            self._json(400, {"ok": False, "error": "bad_request", "message": "必须提供 name"})
            return
        payload = rename_watcher(watch_id, name)
        code = 200 if payload.get("ok") else 400
        if payload.get("error") == "not_found":
            code = 404
        self._json(code, payload)

    def _handle_rules_from_text(self, watch_id: str, data: dict[str, Any]) -> None:
        if not ID_RE.fullmatch(watch_id):
            self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
            return
        text = data.get("text")
        if not isinstance(text, str):
            self._json(400, {"ok": False, "error": "bad_request", "message": "必须提供 text"})
            return
        mode = data.get("mode")
        if mode is not None and mode != "append":
            self._json(400, {"ok": False, "error": "bad_request", "message": "自然语言生成只支持添加新规则"})
            return
        apply = data.get("apply", False)
        if not isinstance(apply, bool):
            self._json(400, {"ok": False, "error": "bad_request", "message": "apply 必须是布尔值"})
            return
        if apply:
            payload = apply_rules_from_text(watch_id, text)
        else:
            payload = preview_rules_from_text(watch_id, text)
        code = 200 if payload.get("ok") else 400
        if payload.get("error") == "not_found":
            code = 404
        self._json(code, payload)

    def _handle_edit_rule_from_text(self, watch_id: str, index: int, data: dict[str, Any]) -> None:
        if not ID_RE.fullmatch(watch_id):
            self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
            return
        text = data.get("text")
        if not isinstance(text, str):
            self._json(400, {"ok": False, "error": "bad_request", "message": "必须提供 text"})
            return
        apply = data.get("apply", False)
        if not isinstance(apply, bool):
            self._json(400, {"ok": False, "error": "bad_request", "message": "apply 必须是布尔值"})
            return
        if apply:
            payload = apply_edit_rule_from_text(watch_id, index, text)
        else:
            payload = preview_edit_rule_from_text(watch_id, index, text)
        code = 200 if payload.get("ok") else 400
        if payload.get("error") == "not_found":
            code = 404
        self._json(code, payload)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 65536:
            return {"ok": False, "error": "bad_json", "message": "请求体过大"}
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": "bad_json", "message": f"JSON 无法解析：{exc}"}
        if not isinstance(data, dict):
            return {"ok": False, "error": "bad_json", "message": "请求体必须是对象"}
        return data

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self._json(404, {"ok": False, "error": "not_found", "message": "页面文件缺失"})
            return
        data = path.read_bytes()
        ctype = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)


def _safe_webui_file(url_path: str) -> Path | None:
    relative = url_path.lstrip("/")
    if not relative or relative.endswith("/"):
        return None
    candidate = (WEBUI_DIR / relative).resolve()
    root = WEBUI_DIR.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def _str_arg(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name)
    if not values:
        return None
    text = values[0].strip()
    return text or None


def _int_arg(query: dict[str, list[str]], name: str, default: int | None = None) -> int | None:
    values = query.get(name)
    if not values:
        return default
    try:
        return int(values[0])
    except ValueError:
        return default


def _bool_arg(query: dict[str, list[str]], name: str) -> bool:
    values = query.get(name)
    if not values:
        return False
    return values[0].lower() in {"1", "true", "yes"}


def _match_watch_id(pattern: str, path: str) -> str | bool | None:
    match = re.fullmatch(pattern, path)
    if not match:
        return None
    watch_id = match.group(1)
    if not ID_RE.fullmatch(watch_id):
        return False
    return watch_id


class WatchWebServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    replaced_pids: list[int]


def serve_state_path() -> Path:
    return state_root() / "serve.json"


def read_serve_state() -> dict[str, Any] | None:
    path = serve_state_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def write_serve_state(host: str, port: int, pid: int) -> None:
    path = serve_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"host": host, "port": port, "pid": pid}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_serve_state(pid: int | None = None) -> None:
    path = serve_state_path()
    if not path.exists():
        return
    if pid is not None:
        state = read_serve_state()
        if state is not None and int(state.get("pid") or 0) != pid:
            return
    try:
        path.unlink()
    except OSError:
        pass


def replace_serve_on_port(port: int) -> list[int]:
    replaced: list[int] = []
    state = read_serve_state()
    if state is not None and int(state.get("port") or -1) == port:
        old = int(state.get("pid") or 0)
        if old and old != os.getpid() and pid_alive(old):
            terminate_pid(old)
            replaced.append(old)
    replaced.extend(claim_listen_port(port))
    return sorted(set(replaced))


def create_server(host: str, port: int, *, replace_existing: bool = True) -> WatchWebServer:
    replaced: list[int] = []
    if replace_existing and port > 0:
        replaced = replace_serve_on_port(port)
    httpd = WatchWebServer((host, port), WatchWebHandler)
    httpd.replaced_pids = replaced
    bound_port = int(httpd.server_address[1])
    if replace_existing and port > 0:
        write_serve_state(host, bound_port, os.getpid())
    return httpd


def serve_http(host: str, port: int) -> WatchWebServer:
    httpd = create_server(host, port, replace_existing=port > 0)
    thread = threading.Thread(target=httpd.serve_forever, name="filewatch-web", daemon=True)
    thread.start()
    httpd.poll_thread = thread  # type: ignore[attr-defined]
    return httpd
