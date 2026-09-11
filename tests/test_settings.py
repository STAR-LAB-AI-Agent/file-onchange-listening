from __future__ import annotations

from pathlib import Path

from filewatch.settings import load_llm_config, mask_secret, public_settings, save_settings, settings_path


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
