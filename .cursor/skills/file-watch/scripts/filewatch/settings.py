from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from filewatch.paths import state_root

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


def public_settings() -> dict[str, Any]:
    cfg = load_llm_config()
    return {
        "ok": True,
        "llm": {
            "base_url": cfg.base_url,
            "model": cfg.model,
            "api_key_set": cfg.configured,
            "api_key_masked": mask_secret(cfg.api_key) if cfg.configured else "",
        },
    }


def _valid_base_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else data
    if not isinstance(llm, dict):
        return {"ok": False, "error": "bad_request", "message": "请求体必须包含 llm 对象"}
    current = load_llm_config()
    stored = _read_file()
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

    payload = {
        "llm": {
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
        }
    }
    _atomic_write(settings_path(), payload)
    return {**public_settings(), "message": "设置已保存"}
