from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse, urlunparse
from urllib.request import Request, urlopen

from filewatch.models import DingTalkTarget

log = logging.getLogger("filewatch.dingtalk")

MAX_MARKDOWN_BYTES = 18000
TYPE_ZH = {
    "created": "新建",
    "modified": "修改",
    "deleted": "删除",
    "moved": "移动",
}

Sender = Callable[[str, str | None, dict[str, Any]], None]
Flushed = Callable[[dict[str, Any]], None]


def signed_webhook(webhook: str, secret: str | None, *, timestamp_ms: int | None = None) -> str:
    if not secret:
        return webhook
    ts = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
    string_to_sign = f"{ts}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    sign = quote_plus(base64.b64encode(digest))
    parsed = urlparse(webhook)
    query = parsed.query
    extra = f"timestamp={ts}&sign={sign}"
    joined = f"{query}&{extra}" if query else extra
    return urlunparse(parsed._replace(query=joined))


def coalesce_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []
    for item in items:
        event = item.get("event") if isinstance(item.get("event"), dict) else {}
        key = (event.get("type"), event.get("path"), event.get("old_path"), item.get("rule"))
        if key not in by_key:
            order.append(key)
        by_key[key] = item
    return [by_key[key] for key in order]


def _fit_utf8(text: str, limit: int = MAX_MARKDOWN_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    omitted = "\n\n… 其余条目已省略"
    budget = max(0, limit - len(omitted.encode("utf-8")))
    cut = encoded[:budget].decode("utf-8", errors="ignore")
    return cut + omitted


def format_markdown(items: list[dict[str, Any]]) -> tuple[str, str]:
    grouped = coalesce_items(items)
    titles = [str(item.get("title") or "").strip() for item in grouped]
    titles = [item for item in titles if item]
    heading = titles[0] if titles and len(set(titles)) == 1 else "文件监听"
    preview = heading[:20] or "文件监听"
    lines = [f"### {heading}", "", f"共 **{len(grouped)}** 条变化", ""]
    for item in grouped:
        message = str(item.get("message") or "").strip()
        event = item.get("event") if isinstance(item.get("event"), dict) else {}
        if not message:
            kind = TYPE_ZH.get(str(event.get("type") or ""), str(event.get("type") or "变化"))
            path = event.get("path") or ""
            message = f"{kind}: `{path}`"
        lines.append(f"- {message}")
    return preview, _fit_utf8("\n".join(lines))


def markdown_payload(title: str, text: str) -> dict[str, Any]:
    return {"msgtype": "markdown", "markdown": {"title": title, "text": text}}


def send_dingtalk(webhook: str, secret: str | None, payload: dict[str, Any]) -> None:
    url = signed_webhook(webhook, secret)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        raw = response.read()
    if not raw:
        return
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"钉钉返回无法解析：{raw[:200]!r}") from exc
    if not isinstance(data, dict):
        return
    errcode = data.get("errcode", 0)
    if errcode:
        raise RuntimeError(f"dingtalk errcode={errcode}: {data.get('errmsg', '')}")


@dataclass
class _Buf:
    target: DingTalkTarget
    items: list[dict[str, Any]] = field(default_factory=list)
    last_tick: int = 0


class DingTalkBatcher:
    """Accumulate notify hits and POST to DingTalk on a polling interval."""

    def __init__(
        self,
        *,
        sender: Sender | None = None,
        on_flushed: Flushed | None = None,
        time_fn: Callable[[], float] | None = None,
        poll_seconds: float = 0.5,
        origin: float | None = None,
    ) -> None:
        self._sender = sender or send_dingtalk
        self._on_flushed = on_flushed
        self._time = time_fn or time.monotonic
        self._poll_seconds = poll_seconds
        self._origin = self._time() if origin is None else origin
        self._lock = threading.Lock()
        self._buffers: dict[tuple[str, str, float], _Buf] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="filewatch-dingtalk", daemon=True)
        self._thread.start()

    def enqueue(self, target: DingTalkTarget, item: dict[str, Any]) -> None:
        key = (target.webhook, target.secret or "", float(target.interval_seconds))
        with self._lock:
            buf = self._buffers.get(key)
            if buf is None:
                buf = _Buf(target=target, last_tick=self._tick(target.interval_seconds))
                self._buffers[key] = buf
            buf.items.append(item)

    def flush_due(self, now: float | None = None) -> int:
        due: list[tuple[DingTalkTarget, list[dict[str, Any]]]] = []
        t = self._time() if now is None else now
        with self._lock:
            for buf in self._buffers.values():
                tick = self._tick(buf.target.interval_seconds, t)
                if buf.items and tick > buf.last_tick:
                    due.append((buf.target, list(buf.items)))
                    buf.items.clear()
                    buf.last_tick = tick
        return self._send_batches(due)

    def flush_all(self) -> int:
        due: list[tuple[DingTalkTarget, list[dict[str, Any]]]] = []
        with self._lock:
            for buf in self._buffers.values():
                if buf.items:
                    due.append((buf.target, list(buf.items)))
                    buf.items.clear()
                    buf.last_tick = self._tick(buf.target.interval_seconds)
        return self._send_batches(due)

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=5)
        self._thread = None
        self.flush_all()

    def _tick(self, interval: float, now: float | None = None) -> int:
        t = self._time() if now is None else now
        if interval <= 0:
            return 0
        return int((t - self._origin) // interval)

    def _loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            try:
                self.flush_due()
            except Exception:  # noqa: BLE001
                log.exception("dingtalk flush failed")

    def _send_batches(self, due: list[tuple[DingTalkTarget, list[dict[str, Any]]]]) -> int:
        sent = 0
        for target, items in due:
            if not items:
                continue
            record = self._post_batch(target, items)
            sent += 1
            if self._on_flushed is not None:
                try:
                    self._on_flushed(record)
                except Exception:  # noqa: BLE001
                    log.exception("dingtalk on_flushed failed")
        return sent

    def _post_batch(self, target: DingTalkTarget, items: list[dict[str, Any]]) -> dict[str, Any]:
        grouped = coalesce_items(items)
        title, text = format_markdown(grouped)
        rules = []
        for item in grouped:
            name = str(item.get("rule") or "")
            if name and name not in rules:
                rules.append(name)
        watch_id = str(grouped[0].get("watch_id") or "") if grouped else ""
        record: dict[str, Any] = {
            "watch_id": watch_id,
            "rule": ",".join(rules),
            "title": title,
            "message": text,
            "count": len(grouped),
            "dingtalk": "ok",
            "status": "ok",
        }
        try:
            self._sender(target.webhook, target.secret, markdown_payload(title, text))
            log.info("dingtalk pushed count=%s rule=%s", len(grouped), record["rule"])
        except Exception as exc:  # noqa: BLE001
            record["status"] = "error"
            record["dingtalk"] = "error"
            record["error"] = str(exc)
            log.warning("dingtalk push failed: %s", exc)
        return record
