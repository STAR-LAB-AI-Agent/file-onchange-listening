from __future__ import annotations

from pathlib import Path

from filewatch.models import DingTalkRef
from filewatch.settings import (
    load_dingtalk_channels,
    load_llm_config,
    load_watch_timing,
    mask_secret,
    public_settings,
    resolve_dingtalk,
    save_settings,
    settings_path,
    probe_dingtalk_from_request,
)


def test_mask_secret() -> None:
    assert mask_secret("short") == "••••"
    assert mask_secret("sk-abcdefghijk") == "sk-••••hijk"


def test_save_and_public_settings_hide_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    result = save_settings(
        {"llm": {"base_url": "https://example.invalid/v1", "model": "demo-model", "api_key": "sk-secret-key-1234"}}
    )
    assert result["ok"] is True
    assert result["llm"]["api_key_set"] is True
    assert "sk-secret-key-1234" not in str(result)
    assert result["llm"]["api_key_masked"].endswith("1234")
    cfg = load_llm_config()
    assert cfg.api_key == "sk-secret-key-1234"
    assert cfg.model == "demo-model"
    assert cfg.wire_api == "chat"
    assert result["llm"]["wire_api"] == "chat"
    public = public_settings()
    assert "sk-secret-key-1234" not in str(public)
    assert settings_path().is_file()


def test_blank_api_key_keeps_existing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    save_settings({"llm": {"api_key": "keep-me-please", "model": "a", "base_url": "https://api.example/v1"}})
    save_settings({"llm": {"api_key": "", "model": "b"}})
    assert load_llm_config().api_key == "keep-me-please"
    assert load_llm_config().model == "b"


def test_clear_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    save_settings({"llm": {"api_key": "gone-soon", "base_url": "https://api.example/v1", "model": "m"}})
    save_settings({"llm": {"clear_api_key": True}})
    assert load_llm_config().api_key == ""


def test_rejects_bad_base_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    result = save_settings({"llm": {"base_url": "not-a-url", "model": "m"}})
    assert result["ok"] is False
    assert result["error"] == "bad_request"


def test_save_dingtalk_channels_and_keep_when_saving_llm(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    save_settings({"llm": {"api_key": "sk-keep-llm", "model": "m", "base_url": "https://api.example/v1"}})
    result = save_settings(
        {
            "dingtalk": {
                "channels": [
                    {
                        "name": "工作群",
                        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
                        "secret": "SECsupersecret",
                        "interval_seconds": 60,
                    }
                ]
            }
        }
    )
    assert result["ok"] is True
    assert "SECsupersecret" not in str(result)
    assert result["dingtalk"]["channels"][0]["secret_set"] is True
    assert result["dingtalk"]["channels"][0]["id"] == "bot"
    assert load_llm_config().api_key == "sk-keep-llm"
    save_settings({"llm": {"model": "other"}})
    channels = load_dingtalk_channels()
    assert len(channels) == 1
    assert channels[0].secret == "SECsupersecret"
    save_settings({"dingtalk": {"channels": [{"id": "bot", "name": "工作群", "webhook": channels[0].webhook, "secret": ""}]}})
    assert load_dingtalk_channels()[0].secret == "SECsupersecret"
    target = resolve_dingtalk(DingTalkRef(channel="bot"))
    assert target.webhook.endswith("access_token=tok")
    assert target.secret == "SECsupersecret"
    default = resolve_dingtalk(DingTalkRef(channel="*"))
    assert default.webhook == target.webhook


def test_dingtalk_rejects_bad_webhook(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    result = save_settings({"dingtalk": {"channels": [{"name": "x", "webhook": "not-a-url"}]}})
    assert result["ok"] is False
    assert result["error"] == "bad_request"


def test_save_dingtalk_frontend_payload_keeps_channel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    payload = {
        "dingtalk": {
            "channels": [
                {
                    "name": "工作群",
                    "webhook": "https://oapi.dingtalk.com/robot/send?access_token=ui-token",
                    "secret": "SECfromui",
                    "interval_seconds": 60,
                }
            ]
        }
    }
    result = save_settings(payload)
    assert result["ok"] is True
    assert len(result["dingtalk"]["channels"]) == 1
    row = result["dingtalk"]["channels"][0]
    assert row["name"] == "工作群"
    assert row["webhook"].endswith("access_token=ui-token")
    assert row["secret_set"] is True
    public = public_settings()
    assert len(public["dingtalk"]["channels"]) == 1
    assert public["dingtalk"]["channels"][0]["id"] == row["id"]
    again = save_settings(
        {
            "dingtalk": {
                "channels": [
                    {
                        "id": row["id"],
                        "name": "工作群",
                        "webhook": row["webhook"],
                        "secret": "",
                        "interval_seconds": 60,
                    }
                ]
            }
        }
    )
    assert again["ok"] is True
    assert len(again["dingtalk"]["channels"]) == 1
    assert load_dingtalk_channels()[0].secret == "SECfromui"


def test_resolve_dingtalk_missing_channel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    try:
        resolve_dingtalk(DingTalkRef(channel="work"))
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "钉钉" in str(exc)
    save_settings(
        {
            "dingtalk": {
                "channels": [
                    {
                        "id": "bot",
                        "name": "默认",
                        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
                    }
                ]
            }
        }
    )
    try:
        resolve_dingtalk(DingTalkRef(channel="missing"))
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "找不到钉钉渠道" in str(exc)


def test_probe_dingtalk_from_request_uses_saved_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    save_settings(
        {
            "dingtalk": {
                "channels": [
                    {
                        "id": "work",
                        "name": "工作群",
                        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=saved",
                        "secret": "SECsaved",
                    }
                ]
            }
        }
    )
    posted: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append((webhook, secret)),
    )
    result = probe_dingtalk_from_request({"id": "work", "webhook": "", "secret": "", "name": ""})
    assert result["ok"] is True
    assert posted == [("https://oapi.dingtalk.com/robot/send?access_token=saved", "SECsaved")]
    posted.clear()
    result = probe_dingtalk_from_request(
        {
            "id": "work",
            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=draft",
            "secret": "SECdraft",
            "name": "草稿群",
        }
    )
    assert result["ok"] is True
    assert posted == [("https://oapi.dingtalk.com/robot/send?access_token=draft", "SECdraft")]
    assert "草稿群" in result["message"]


def test_watch_timing_defaults_and_save(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    public = public_settings()
    assert public["watch"]["debounce_ms"] == 400
    assert public["watch"]["line_diff_quiet_ms"] == 30_000
    assert public["watch"]["line_diff_max_bytes"] == 256 * 1024
    timing = load_watch_timing()
    assert timing.debounce_ms == 400
    assert timing.line_diff_quiet_ms == 30_000
    assert timing.line_diff_max_bytes == 256 * 1024
    result = save_settings({"watch": {"debounce_ms": 250, "line_diff_quiet_ms": 12_000, "line_diff_max_bytes": 1024}})
    assert result["ok"] is True
    assert result["watch"]["debounce_ms"] == 250
    assert result["watch"]["line_diff_quiet_ms"] == 12_000
    assert result["watch"]["line_diff_max_bytes"] == 1024
    save_settings({"llm": {"model": "kept", "base_url": "https://api.example/v1"}})
    again = load_watch_timing()
    assert again.debounce_ms == 250
    assert again.line_diff_quiet_ms == 12_000
    assert again.line_diff_max_bytes == 1024
    assert load_llm_config().model == "kept"


def test_watch_timing_rejects_negative(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    result = save_settings({"watch": {"debounce_ms": -1}})
    assert result["ok"] is False
    assert result["error"] == "bad_request"
    result = save_settings({"watch": {"line_diff_quiet_ms": "nope"}})
    assert result["ok"] is False
    result = save_settings({"watch": {"line_diff_max_bytes": 0}})
    assert result["ok"] is False


def test_save_and_keep_wire_api(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    monkeypatch.delenv("FILEWATCH_LLM_WIRE_API", raising=False)
    result = save_settings(
        {
            "llm": {
                "base_url": "https://api.anthropic.com/v1",
                "model": "claude-sonnet-4-5",
                "api_key": "sk-ant",
                "wire_api": "messages",
            }
        }
    )
    assert result["ok"] is True
    assert result["llm"]["wire_api"] == "anthropic"
    assert load_llm_config().wire_api == "anthropic"
    save_settings({"llm": {"model": "claude-opus-4-6"}})
    assert load_llm_config().wire_api == "anthropic"
    assert load_llm_config().model == "claude-opus-4-6"
    rejected = save_settings({"llm": {"wire_api": "soap"}})
    assert rejected["ok"] is False
    assert rejected["error"] == "bad_request"
    save_settings({"llm": {"wire_api": "openai-responses"}})
    assert load_llm_config().wire_api == "responses"


def test_wire_api_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    monkeypatch.setenv("FILEWATCH_LLM_WIRE_API", "anthropic")
    assert load_llm_config().wire_api == "anthropic"
