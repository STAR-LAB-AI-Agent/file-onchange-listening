from __future__ import annotations

from pathlib import Path

from filewatch.models import DingTalkRef
from filewatch.settings import (
    load_dingtalk_channels,
    load_llm_config,
    mask_secret,
    public_settings,
    resolve_dingtalk,
    save_settings,
    settings_path,
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
