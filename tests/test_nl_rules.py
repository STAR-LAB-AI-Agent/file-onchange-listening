from __future__ import annotations

import json

from filewatch.nl_rules import edit_rule_from_text, extract_json_object, merge_rules, rules_from_text


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


def test_yaml_active_window_is_parsed() -> None:
    text = """
- name: workday
  when:
    types: [created]
    glob: ["**/*"]
    active:
      start: "09:00"
      end: "18:00"
      days: [mon, tue, wed, thu, fri]
  then:
    - notify:
        title: t
        message: "{{filename}}"
"""
    result = rules_from_text(text)
    assert result["ok"] is True
    assert result["rules"][0]["when"]["active"]["start"] == "09:00"
    assert result["rules"][0]["when"]["active"]["days"] == ["mon", "tue", "wed", "thu", "fri"]


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


def test_llm_replace_payload_still_appends() -> None:
    result = rules_from_text(
        "所有文件 POST https://example.invalid/hook",
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
    assert result["mode"] == "append"
    assert result["rules"][0]["then"][0]["notify"]["webhook"] == "https://example.invalid/hook"


def test_yaml_dingtalk_is_parsed() -> None:
    text = """
- name: ding
  when:
    types: [created, modified]
    glob: ["**/*"]
    is_dir: false
  then:
    - notify:
        title: 文件有变化
        message: "{{type}}: {{path}}"
        dingtalk:
          webhook: "https://oapi.dingtalk.com/robot/send?access_token=tok"
          secret: "SECxxx"
"""
    result = rules_from_text(text)
    assert result["ok"] is True
    ding = result["rules"][0]["then"][0]["notify"]["dingtalk"]
    assert ding["webhook"].startswith("https://oapi.dingtalk.com/")
    assert ding["secret"] == "SECxxx"


def test_yaml_dingtalk_channel_is_parsed() -> None:
    text = """
- name: ding
  when:
    types: [created]
    glob: ["**/*"]
  then:
    - notify:
        title: 文件有变化
        message: "{{type}}: {{path}}"
        dingtalk: true
"""
    result = rules_from_text(text)
    assert result["ok"] is True
    assert result["rules"][0]["then"][0]["notify"]["dingtalk"] is True


def test_llm_fenced_json_is_parsed() -> None:
    def complete(_system: str, _user: str) -> str:
        return '```json\n{"mode":"append","rules":[{"name":"x","when":{"types":["deleted"],"glob":["**/*.png"]},"then":[{"notify":{"title":"t","message":"{{filename}}"}}]}]}\n```'

    result = rules_from_text("删除图片", complete=complete)
    assert result["ok"] is True
    assert result["rules"][0]["when"]["glob"] == ["**/*.png"]


def test_extract_json_object_from_prose() -> None:
    data = extract_json_object('说明如下 {"mode": "append", "rules": [] } 结束')
    assert data["mode"] == "append"


def test_merge_always_appends() -> None:
    existing = [{"name": "a", "when": {}, "then": [{"notify": {}}]}]
    generated = [{"name": "b", "when": {"glob": ["**/*.md"]}, "then": [{"notify": {"title": "x"}}]}]
    merged = merge_rules(existing, generated)
    assert [item["name"] for item in merged] == ["a", "b"]


def test_merge_same_name_still_appends() -> None:
    existing = [{"name": "a", "when": {}, "then": [{"notify": {}}]}]
    generated = [{"name": "a", "when": {"glob": ["**/*.md"]}, "then": [{"notify": {"title": "x"}}]}]
    merged = merge_rules(existing, generated, "replace")
    assert len(merged) == 2
    assert merged[1]["when"]["glob"] == ["**/*.md"]


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


def test_llm_garbage_is_bad_config() -> None:
    calls: list[str] = []

    def complete(_system: str, user: str) -> str:
        calls.append(user)
        return "抱歉，我不能输出 JSON"

    result = rules_from_text("新建 markdown", complete=complete)
    assert result["ok"] is False
    assert result["error"] == "bad_config"
    assert result["retried"] is True
    assert len(calls) == 2
    assert "错误原因" in calls[1]
    assert "抱歉，我不能输出 JSON" in calls[1]


def test_llm_retries_once_then_succeeds() -> None:
    calls: list[str] = []
    good = {
        "notes": ["已修正"],
        "rules": [
            {
                "name": "change-md",
                "when": {"types": ["created", "modified"], "glob": ["**/*.md"], "is_dir": False},
                "then": [{"notify": {"title": "Markdown 有变化", "message": "{{type}}: {{path}}"}}],
            }
        ],
    }

    def complete(_system: str, user: str) -> str:
        calls.append(user)
        if len(calls) == 1:
            return "不是 JSON"
        return json.dumps(good)

    result = rules_from_text("新建 markdown 时通知我", complete=complete)
    assert result["ok"] is True
    assert result["retried"] is True
    assert "已根据上次错误重试并修正" in result["notes"]
    assert result["rules"][0]["name"] == "change-md"
    assert len(calls) == 2
    assert "错误码：bad_config" in calls[1]


def test_llm_not_configured_does_not_retry() -> None:
    from filewatch.llm import LlmError

    calls = {"n": 0}

    def complete(_system: str, _user: str) -> str:
        calls["n"] += 1
        raise LlmError("llm_not_configured", "请先在设置页填写 LLM API Key")

    result = rules_from_text("新建 markdown 时通知我", complete=complete)
    assert result["ok"] is False
    assert result["error"] == "llm_not_configured"
    assert "retried" not in result
    assert calls["n"] == 1


def test_yaml_exclude_rule_is_parsed() -> None:
    text = """
- name: skip-logs
  exclude: true
  when:
    glob: ["**/*.log"]
"""
    result = rules_from_text(text)
    assert result["ok"] is True
    rule = result["rules"][0]
    assert rule["exclude"] is True
    assert rule["when"]["glob"] == ["**/*.log"]
    assert rule.get("then") in (None, [])


def test_llm_generates_exclude_rule() -> None:
    result = rules_from_text(
        "不要监听 log 文件",
        complete=_llm(
            {
                "mode": "append",
                "notes": ["排除日志"],
                "rules": [
                    {
                        "name": "skip-logs",
                        "exclude": True,
                        "when": {"types": ["created", "modified", "deleted", "moved"], "glob": ["**/*.log"]},
                        "then": [],
                    }
                ],
            }
        ),
    )
    assert result["ok"] is True
    rule = result["rules"][0]
    assert rule["exclude"] is True
    assert rule["then"] == []
    assert "**/*.log" in rule["when"]["glob"]


def _notify_rule(name: str = "change-md", glob: str = "**/*.md") -> dict:
    return {
        "name": name,
        "enabled": True,
        "exclude": False,
        "when": {"types": ["created", "modified"], "glob": [glob], "is_dir": False, "cooldown_seconds": 0},
        "then": [{"notify": {"title": "文件有变化", "message": "{{type}}: {{path}}"}}],
    }


def test_edit_rule_from_text_updates_fields() -> None:
    result = edit_rule_from_text(
        "改成只匹配 txt，冷却 30 秒",
        current=_notify_rule(),
        existing_names=["change-md", "other"],
        complete=_llm(
            {
                "notes": ["改 glob"],
                "rule": {
                    "name": "change-md",
                    "enabled": True,
                    "exclude": False,
                    "when": {
                        "types": ["created", "modified"],
                        "glob": ["**/*.txt"],
                        "is_dir": False,
                        "cooldown_seconds": 30,
                    },
                    "then": [{"notify": {"title": "文件有变化", "message": "{{type}}: {{path}}"}}],
                },
            }
        ),
    )
    assert result["ok"] is True
    assert result["rule"]["name"] == "change-md"
    assert result["rule"]["when"]["glob"] == ["**/*.txt"]
    assert result["rule"]["when"]["cooldown_seconds"] == 30
    assert result["notes"][0] == "由 LLM 编辑"


def test_edit_rule_keeps_name_when_taken() -> None:
    result = edit_rule_from_text(
        "改名成 other",
        current=_notify_rule("change-md"),
        existing_names=["change-md", "other"],
        complete=_llm({"rule": _notify_rule("other", "**/*.txt")}),
    )
    assert result["ok"] is True
    assert result["rule"]["name"] != "other"
    assert result["rule"]["name"].startswith("other")


def test_edit_yaml_blob_replaces_current() -> None:
    result = edit_rule_from_text(
        "- name: skip-logs\n  exclude: true\n  when:\n    glob: ['**/*.log']\n",
        current=_notify_rule(),
    )
    assert result["ok"] is True
    assert result["rule"]["exclude"] is True
    assert result["rule"]["when"]["glob"] == ["**/*.log"]
    assert result["rule"].get("then") in (None, [])


def test_edit_empty_text() -> None:
    result = edit_rule_from_text("   ", current=_notify_rule())
    assert result["ok"] is False
    assert result["error"] == "empty_text"


def test_edit_rule_retries_once_then_succeeds() -> None:
    calls: list[str] = []
    fixed = _notify_rule()
    fixed["when"]["glob"] = ["**/*.txt"]

    def complete(_system: str, user: str) -> str:
        calls.append(user)
        if len(calls) == 1:
            return "not json at all"
        return json.dumps({"notes": ["已改 glob"], "rule": fixed})

    result = edit_rule_from_text(
        "改成只匹配 txt",
        current=_notify_rule(),
        existing_names=["change-md"],
        complete=complete,
    )
    assert result["ok"] is True
    assert result["retried"] is True
    assert result["rule"]["when"]["glob"] == ["**/*.txt"]
    assert len(calls) == 2
    assert "上次模型输出" in calls[1]
