from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from filewatch.llm import test_llm_connection
from filewatch.service import (
    apply_rules_from_text,
    describe_watcher,
    list_watcher_payloads,
    preview_rules_from_text,
    read_stream,
    save_rules,
    start_path,
    stop_watch,
    store_for,
    watcher_config,
)
from filewatch.settings import public_settings, save_settings

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
        if " /api/" in f" {line}" and "/events" in line:
            return
        log.info("%s - %s", self.address_string(), line)

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
            if not store.config_path.exists() and not store.events_path.exists():
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
            if not store.config_path.exists() and not store.events_path.exists():
                self._json(404, {"ok": False, "error": "not_found", "message": f"没有找到监听 {watch_id}"})
                return
            since = _int_arg(query, "since")
            limit = _int_arg(query, "limit", 100) or 100
            limit = max(1, min(limit, 500))
            tail = _bool_arg(query, "tail")
            payload = read_stream(watch_id, "events", since=since, limit=limit, tail=tail)
            self._json(200 if payload.get("ok") else 400, payload)
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
        if path == "/api/watchers/start":
            folder = data.get("path")
            if not folder or not isinstance(folder, str):
                self._json(400, {"ok": False, "error": "bad_request", "message": "必须提供 path"})
                return
            watch_id = data.get("id")
            if watch_id is not None and not isinstance(watch_id, str):
                self._json(400, {"ok": False, "error": "bad_request", "message": "id 必须是字符串"})
                return
            recursive = data.get("recursive", True)
            if not isinstance(recursive, bool):
                self._json(400, {"ok": False, "error": "bad_request", "message": "recursive 必须是布尔值"})
                return
            payload = start_path(folder, watch_id=watch_id, recursive=recursive, reuse=True)
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
        match = re.fullmatch(r"/api/watchers/([^/]+)/rules/from-text", path)
        if match:
            self._handle_rules_from_text(match.group(1), data)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/rules", path)
        if match:
            self._handle_save_rules(match.group(1), data)
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
            self._json(200 if payload.get("ok") else 400, payload)
            return
        match = re.fullmatch(r"/api/watchers/([^/]+)/rules", path)
        if match:
            self._handle_save_rules(match.group(1), data)
            return
        self._json(404, {"ok": False, "error": "not_found", "message": "未知路径"})

    def _handle_save_rules(self, watch_id: str, data: dict[str, Any]) -> None:
        if not ID_RE.fullmatch(watch_id):
            self._json(400, {"ok": False, "error": "bad_id", "message": "watch_id 无效"})
            return
        payload = save_rules(watch_id, data.get("rules"))
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
        if mode is not None and mode not in {"append", "replace"}:
            self._json(400, {"ok": False, "error": "bad_request", "message": "mode 必须是 append 或 replace"})
            return
        apply = data.get("apply", False)
        if not isinstance(apply, bool):
            self._json(400, {"ok": False, "error": "bad_request", "message": "apply 必须是布尔值"})
            return
        if apply:
            payload = apply_rules_from_text(watch_id, text, mode=mode)
        else:
            payload = preview_rules_from_text(watch_id, text, mode=mode)
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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


def create_server(host: str, port: int) -> WatchWebServer:
    return WatchWebServer((host, port), WatchWebHandler)


def serve_http(host: str, port: int) -> WatchWebServer:
    httpd = create_server(host, port)
    thread = threading.Thread(target=httpd.serve_forever, name="filewatch-web", daemon=True)
    thread.start()
    httpd.poll_thread = thread  # type: ignore[attr-defined]
    return httpd
