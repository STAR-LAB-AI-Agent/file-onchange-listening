from __future__ import annotations

import json

from filewatch.nl_rules import extract_json_object, merge_rules, rules_from_text


def _llm(payload: dict):
    def complete(_system: str, _user: str) -> str:
        return json.dumps(payload)

    return complete


def test_yaml_blob_is_parsed() -> None:
    text = """
- name: custom
  when:
    types: [created]
    glob: ["**/*.log"]
  then:
    - notify:
        title: log
        message: "{{filename}}"
"""
    result = rules_from_text(text)
    assert result["ok"] is True
    assert result["rules"][0]["name"] == "custom"
    assert result["rules"][0]["when"]["glob"] == ["**/*.log"]


def test_invalid_yaml_rule_returns_bad_config() -> None:
    result = rules_from_text("- name: x\n  then: []\n")
    assert result["ok"] is False
    assert result["error"] == "bad_config"


def test_empty_text() -> None:
    result = rules_from_text("   ")
    assert result["ok"] is False
    assert result["error"] == "empty_text"


def test_unstructured_requires_llm(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    result = rules_from_text("新建 markdown 时通知我")
    assert result["ok"] is False
    assert result["error"] == "llm_not_configured"


def test_llm_generates_markdown_rule() -> None:
    result = rules_from_text(
        "新建或修改 markdown 时通知我",
        complete=_llm(
            {
                "mode": "append",
                "notes": ["匹配 md"],
                "rules": [
                    {
                        "name": "change-md",
                        "when": {"types": ["created", "modified"], "glob": ["**/*.md"], "is_dir": False},
                        "then": [{"notify": {"title": "Markdown 有变化", "message": "{{type}}: {{path}}"}}],
                    }
                ],
            }
        ),
    )
    assert result["ok"] is True
    rule = result["rules"][0]
    assert rule["when"]["types"] == ["created", "modified"]
    assert "**/*.md" in rule["when"]["glob"]
    assert "notify" in rule["then"][0]


def test_llm_replace_and_webhook() -> None:
    result = rules_from_text(
        "替换：所有文件 POST https://example.invalid/hook",
        complete=_llm(
            {
                "mode": "replace",
                "rules": [
                    {
                        "name": "any-file",
                        "when": {"types": ["created", "modified"], "glob": ["**/*"], "is_dir": False},
                        "then": [
                            {
                                "notify": {
                                    "title": "变化",
                                    "message": "{{path}}",
                                    "webhook": "https://example.invalid/hook",
                                }
                            }
                        ],
                    }
                ],
            }
        ),
    )
    assert result["mode"] == "replace"
    assert result["rules"][0]["then"][0]["notify"]["webhook"] == "https://example.invalid/hook"


def test_llm_fenced_json_is_parsed() -> None:
    def complete(_system: str, _user: str) -> str:
        return '```json\n{"mode":"append","rules":[{"name":"x","when":{"types":["deleted"],"glob":["**/*.png"]},"then":[{"notify":{"title":"t","message":"{{filename}}"}}]}]}\n```'

    result = rules_from_text("删除图片", complete=complete)
    assert result["ok"] is True
    assert result["rules"][0]["when"]["glob"] == ["**/*.png"]


def test_extract_json_object_from_prose() -> None:
    data = extract_json_object('说明如下 {"mode": "append", "rules": [] } 结束')
    assert data["mode"] == "append"


def test_merge_append_replaces_same_name() -> None:
    existing = [{"name": "a", "when": {}, "then": [{"notify": {}}]}]
    generated = [{"name": "a", "when": {"glob": ["**/*.md"]}, "then": [{"notify": {"title": "x"}}]}]
    merged = merge_rules(existing, generated, "append")
    assert len(merged) == 1
    assert merged[0]["when"]["glob"] == ["**/*.md"]


def test_unique_name_when_appending() -> None:
    result = rules_from_text(
        "新建 markdown",
        existing_names=["created-md"],
        complete=_llm(
            {
                "mode": "append",
                "rules": [
                    {
                        "name": "created-md",
                        "when": {"types": ["created"], "glob": ["**/*.md"], "is_dir": False},
                        "then": [{"notify": {"title": "t", "message": "{{filename}}"}}],
                    }
                ],
            }
        ),
    )
    assert result["rules"][0]["name"] != "created-md"
    assert result["rules"][0]["name"].startswith("created-md")
