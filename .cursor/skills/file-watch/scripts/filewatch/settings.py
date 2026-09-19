from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from filewatch.models import (
    DEFAULT_DEBOUNCE_MS,
    DEFAULT_DINGTALK_CHANNEL,
    DEFAULT_LINE_DIFF_MAX_BYTES,
    DEFAULT_LINE_DIFF_QUIET_MS,
    DingTalkRef,
    DingTalkTarget,
)
from filewatch.paths import sanitize_id, state_root

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class DingTalkChannel:
    id: str
    name: str
    webhook: str
    secret: str = ""
    interval_seconds: float = 60.0


@dataclass(frozen=True)
class WatchTiming:
    debounce_ms: int = DEFAULT_DEBOUNCE_MS
    line_diff_quiet_ms: int = DEFAULT_LINE_DIFF_QUIET_MS
    line_diff_max_bytes: int = DEFAULT_LINE_DIFF_MAX_BYTES


def settings_path() -> Path:
    return state_root() / "settings.json"


def mask_secret(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "••••"
    return f"{text[:3]}••••{text[-4:]}"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _read_file() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_llm_config() -> LlmConfig:
    data = _read_file()
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    base_url = str(llm.get("base_url") or os.environ.get("FILEWATCH_LLM_BASE_URL") or DEFAULT_BASE_URL).strip()
    api_key = str(llm.get("api_key") or os.environ.get("FILEWATCH_LLM_API_KEY") or "").strip()
    model = str(llm.get("model") or os.environ.get("FILEWATCH_LLM_MODEL") or DEFAULT_MODEL).strip()
    return LlmConfig(base_url=base_url.rstrip("/"), api_key=api_key, model=model or DEFAULT_MODEL)


def _valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _valid_base_url(url: str) -> bool:
    return _valid_http_url(url)


def _llm_store_from_file(stored: dict[str, Any]) -> dict[str, Any]:
    llm = stored.get("llm") if isinstance(stored.get("llm"), dict) else {}
    return {
        "base_url": str(llm.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/") or DEFAULT_BASE_URL,
        "model": str(llm.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "api_key": str(llm.get("api_key") or "").strip(),
    }


def _dingtalk_store_from_file(stored: dict[str, Any]) -> dict[str, Any]:
    raw = stored.get("dingtalk")
    if isinstance(raw, dict) and isinstance(raw.get("channels"), list):
        return {"channels": [item for item in raw["channels"] if isinstance(item, dict)]}
    if isinstance(raw, list):
        return {"channels": [item for item in raw if isinstance(item, dict)]}
    return {"channels": []}


def _channel_id(name: str, taken: set[str], explicit: str | None = None) -> str:
    raw = (explicit or name or "").strip()
    try:
        slug = sanitize_id(raw) if raw else ""
    except ValueError:
        slug = ""
    if not slug:
        slug = "bot"
    base = slug
    index = 2
    while slug in taken:
        slug = f"{base}-{index}"
        index += 1
    return slug


def _parse_interval(raw: Any, *, field: str) -> tuple[float | None, str | None]:
    if raw is None or raw == "":
        return 60.0, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, f"{field} 必须是数字"
    if value <= 0:
        return None, f"{field} 必须大于 0"
    return value, None


def _parse_int(raw: Any, *, field: str, default: int, min_value: int = 0) -> tuple[int | None, str | None]:
    if raw is None or raw == "":
        return default, None
    try:
        if isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()):
            return None, f"{field} 必须是整数"
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"{field} 必须是整数"
    if value < min_value:
        return None, f"{field} 必须 >= {min_value}"
    return value, None


def _watch_store_from_file(stored: dict[str, Any]) -> dict[str, Any]:
    raw = stored.get("watch") if isinstance(stored.get("watch"), dict) else {}
    debounce, debounce_err = _parse_int(
        raw.get("debounce_ms", DEFAULT_DEBOUNCE_MS), field="debounce_ms", default=DEFAULT_DEBOUNCE_MS
    )
    quiet, quiet_err = _parse_int(
        raw.get("line_diff_quiet_ms", DEFAULT_LINE_DIFF_QUIET_MS),
        field="line_diff_quiet_ms",
        default=DEFAULT_LINE_DIFF_QUIET_MS,
    )
    max_bytes, max_err = _parse_int(
        raw.get("line_diff_max_bytes", DEFAULT_LINE_DIFF_MAX_BYTES),
        field="line_diff_max_bytes",
        default=DEFAULT_LINE_DIFF_MAX_BYTES,
        min_value=1,
    )
    return {
        "debounce_ms": DEFAULT_DEBOUNCE_MS if debounce is None or debounce_err else debounce,
        "line_diff_quiet_ms": DEFAULT_LINE_DIFF_QUIET_MS if quiet is None or quiet_err else quiet,
        "line_diff_max_bytes": DEFAULT_LINE_DIFF_MAX_BYTES if max_bytes is None or max_err else max_bytes,
    }


def load_watch_timing() -> WatchTiming:
    stored = _watch_store_from_file(_read_file())
    return WatchTiming(
        debounce_ms=stored["debounce_ms"],
        line_diff_quiet_ms=stored["line_diff_quiet_ms"],
        line_diff_max_bytes=stored["line_diff_max_bytes"],
    )


def load_dingtalk_channels() -> tuple[DingTalkChannel, ...]:
    stored = _dingtalk_store_from_file(_read_file())
    channels: list[DingTalkChannel] = []
    taken: set[str] = set()
    for item in stored["channels"]:
        webhook = str(item.get("webhook") or "").strip()
        if not webhook:
            continue
        name = str(item.get("name") or "").strip() or "钉钉群"
        channel_id = _channel_id(name, taken, str(item.get("id") or "") or None)
        taken.add(channel_id)
        interval, err = _parse_interval(item.get("interval_seconds", 60), field="interval_seconds")
        channels.append(
            DingTalkChannel(
                id=channel_id,
                name=name,
                webhook=webhook,
                secret=str(item.get("secret") or "").strip(),
                interval_seconds=60.0 if interval is None or err else interval,
            )
        )
    return tuple(channels)


def resolve_dingtalk(ref: DingTalkRef | None) -> DingTalkTarget:
    if ref is None or not ref.enabled:
        raise RuntimeError("钉钉未启用")
    inline = ref.inline_target()
    if inline is not None:
        return inline
    channels = load_dingtalk_channels()
    if not channels:
        raise RuntimeError("未在设置中配置钉钉机器人")
    key = (ref.channel or "").strip()
    if key in {"", DEFAULT_DINGTALK_CHANNEL, "default"}:
        chosen = channels[0]
    else:
        chosen = next((item for item in channels if item.id == key), None)
        if chosen is None:
            chosen = next((item for item in channels if item.name == key), None)
        if chosen is None:
            raise RuntimeError(f"找不到钉钉渠道：{key}")
    return DingTalkTarget(
        webhook=chosen.webhook,
        secret=chosen.secret or None,
        interval_seconds=chosen.interval_seconds,
    )


def _public_channels() -> list[dict[str, Any]]:
    rows = []
    for item in load_dingtalk_channels():
        secret_set = bool(item.secret)
        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "webhook": item.webhook,
                "secret_set": secret_set,
                "secret_masked": mask_secret(item.secret) if secret_set else "",
                "interval_seconds": item.interval_seconds,
            }
        )
    return rows


def public_settings() -> dict[str, Any]:
    cfg = load_llm_config()
    timing = load_watch_timing()
    return {
        "ok": True,
        "llm": {
            "base_url": cfg.base_url,
            "model": cfg.model,
            "api_key_set": cfg.configured,
            "api_key_masked": mask_secret(cfg.api_key) if cfg.configured else "",
        },
        "dingtalk": {"channels": _public_channels()},
        "watch": {
            "debounce_ms": timing.debounce_ms,
            "line_diff_quiet_ms": timing.line_diff_quiet_ms,
            "line_diff_max_bytes": timing.line_diff_max_bytes,
        },
    }


def _merge_llm(llm: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    current = load_llm_config()
    stored_llm = stored.get("llm") if isinstance(stored.get("llm"), dict) else {}
    file_key = str(stored_llm.get("api_key") or "").strip()

    if "base_url" in llm:
        base_url = str(llm.get("base_url") or "").strip().rstrip("/")
    else:
        base_url = current.base_url
    if not base_url:
        base_url = DEFAULT_BASE_URL
    if not _valid_base_url(base_url):
        return {"ok": False, "error": "bad_request", "message": "base_url 必须是 http(s) 地址"}

    if "model" in llm:
        model = str(llm.get("model") or "").strip()
    else:
        model = current.model
    if not model:
        return {"ok": False, "error": "bad_request", "message": "model 不能为空"}

    clear = bool(llm.get("clear_api_key"))
    incoming = llm.get("api_key")
    if clear:
        api_key = ""
    elif incoming is None:
        api_key = file_key
    elif not isinstance(incoming, str):
        return {"ok": False, "error": "bad_request", "message": "api_key 必须是字符串"}
    else:
        api_key = incoming.strip() or file_key

    return {"ok": True, "llm": {"base_url": base_url, "model": model, "api_key": api_key}}


def _merge_dingtalk(raw: Any, stored: dict[str, Any]) -> dict[str, Any]:
    existing = {item.id: item for item in load_dingtalk_channels()}
    if raw is None:
        return {"ok": True, "dingtalk": _dingtalk_store_from_file(stored)}
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("channels")
        if items is None:
            items = []
    else:
        return {"ok": False, "error": "bad_request", "message": "dingtalk 必须是对象或渠道列表"}
    if not isinstance(items, list):
        return {"ok": False, "error": "bad_request", "message": "dingtalk.channels 必须是列表"}

    channels: list[dict[str, Any]] = []
    taken: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return {"ok": False, "error": "bad_request", "message": f"钉钉渠道[{index}] 必须是对象"}
        webhook = str(item.get("webhook") or "").strip()
        if not webhook:
            return {"ok": False, "error": "bad_request", "message": "钉钉 Webhook 不能为空"}
        if not _valid_http_url(webhook):
            return {"ok": False, "error": "bad_request", "message": "钉钉 Webhook 必须是 http(s) 地址"}
        name = str(item.get("name") or "").strip() or "钉钉群"
        channel_id = _channel_id(name, taken, str(item.get("id") or "") or None)
        taken.add(channel_id)
        interval, err = _parse_interval(item.get("interval_seconds", 60), field="钉钉汇总间隔")
        if err:
            return {"ok": False, "error": "bad_request", "message": err}
        prev = existing.get(channel_id)
        clear = bool(item.get("clear_secret"))
        incoming = item.get("secret")
        if clear:
            secret = ""
        elif incoming is None:
            secret = prev.secret if prev else ""
        elif not isinstance(incoming, str):
            return {"ok": False, "error": "bad_request", "message": "钉钉 SEC 必须是字符串"}
        else:
            secret = incoming.strip() or (prev.secret if prev else "")
        channels.append(
            {
                "id": channel_id,
                "name": name,
                "webhook": webhook,
                "secret": secret,
                "interval_seconds": interval if interval is not None else 60.0,
            }
        )
    return {"ok": True, "dingtalk": {"channels": channels}}


def _merge_watch(raw: Any, stored: dict[str, Any]) -> dict[str, Any]:
    current = _watch_store_from_file(stored)
    if raw is None:
        return {"ok": True, "watch": current}
    if not isinstance(raw, dict):
        return {"ok": False, "error": "bad_request", "message": "watch 必须是对象"}
    debounce, debounce_err = _parse_int(
        raw.get("debounce_ms", current["debounce_ms"]),
        field="事件入账间隔",
        default=current["debounce_ms"],
    )
    if debounce_err:
        return {"ok": False, "error": "bad_request", "message": debounce_err}
    quiet, quiet_err = _parse_int(
        raw.get("line_diff_quiet_ms", current["line_diff_quiet_ms"]),
        field="行级快照等待",
        default=current["line_diff_quiet_ms"],
    )
    if quiet_err:
        return {"ok": False, "error": "bad_request", "message": quiet_err}
    max_bytes, max_err = _parse_int(
        raw.get("line_diff_max_bytes", current["line_diff_max_bytes"]),
        field="行级快照最大文件",
        default=current["line_diff_max_bytes"],
        min_value=1,
    )
    if max_err:
        return {"ok": False, "error": "bad_request", "message": max_err}
    return {
        "ok": True,
        "watch": {
            "debounce_ms": debounce if debounce is not None else DEFAULT_DEBOUNCE_MS,
            "line_diff_quiet_ms": quiet if quiet is not None else DEFAULT_LINE_DIFF_QUIET_MS,
            "line_diff_max_bytes": max_bytes if max_bytes is not None else DEFAULT_LINE_DIFF_MAX_BYTES,
        },
    }


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"ok": False, "error": "bad_request", "message": "请求体必须是对象"}
    has_llm_key = isinstance(data.get("llm"), dict)
    has_ding_key = "dingtalk" in data
    has_watch_key = "watch" in data
    looks_like_llm = any(key in data for key in ("base_url", "model", "api_key", "clear_api_key"))
    if not has_llm_key and not has_ding_key and not has_watch_key and not looks_like_llm:
        return {"ok": False, "error": "bad_request", "message": "请求体必须包含 llm、dingtalk 或 watch"}

    stored = _read_file()
    if has_llm_key or looks_like_llm:
        llm_in = data["llm"] if has_llm_key else data
        merged_llm = _merge_llm(llm_in, stored)
        if not merged_llm.get("ok"):
            return merged_llm
        llm_store = merged_llm["llm"]
    else:
        llm_store = _llm_store_from_file(stored)

    if has_ding_key:
        merged_ding = _merge_dingtalk(data.get("dingtalk"), stored)
        if not merged_ding.get("ok"):
            return merged_ding
        ding_store = merged_ding["dingtalk"]
    else:
        ding_store = _dingtalk_store_from_file(stored)

    if has_watch_key:
        merged_watch = _merge_watch(data.get("watch"), stored)
        if not merged_watch.get("ok"):
            return merged_watch
        watch_store = merged_watch["watch"]
    else:
        watch_store = _watch_store_from_file(stored)

    _atomic_write(settings_path(), {"llm": llm_store, "dingtalk": ding_store, "watch": watch_store})
    return {**public_settings(), "message": "设置已保存"}
