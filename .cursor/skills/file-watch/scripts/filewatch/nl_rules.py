from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from filewatch.config import ConfigError, parse_config_dict
from filewatch.llm import LlmError, chat_complete
from filewatch.paths import sanitize_id

SYSTEM_PROMPT = """你是 filewatch 规则编译器。把用户口语转成 JSON，只输出一个 JSON 对象，不要 markdown。
格式：
{"mode":"append"|"replace","notes":["中文说明"],"warnings":[],"rules":[{
  "name":"小写短横线英文id","enabled":true,
  "when":{"types":["created"],"glob":["**/*.md"],"regex":null,"is_dir":false,"min_size_bytes":null,"cooldown_seconds":0},
  "then":[{"notify":{"title":"...","message":"{{type}}: {{path}}","webhook":null,"mailbox":true,"dingtalk":null}}]
}]}
约束：
- when.types 只能是 created / modified / deleted / moved
- 递归 glob 写 **/*.ext，不要只写 *.ext
- 用户没说任务要求/启动智能体/处理文件时，then 只含 notify
- 用户提到钉钉/群机器人时，notify.dingtalk 填写 webhook 与 secret（SEC 加签），interval_seconds 默认 60；未给地址则 dingtalk 为 null
- 钉钉是按分钟汇总推送，不要改成即时 webhook
- 用户说了要做什么（重写、处理、启动智能体、按格式改写等）时，then 追加 agent：{"agent":{"runner":"builtin","prompt":"完整任务要求（可用模板变量）","timeout_seconds":600,"max_steps":24,"command":null,"cwd":null,"model":null}}
- agent.runner 默认 builtin（调用设置页 LLM）；高级用法才用 command（须 command 字符串数组）或 cursor_sdk
- 模板变量只能用 {{path}} {{filename}} {{type}} {{watch_id}} {{ts}} {{old_path}} {{json}} {{rule}}
- 未指定类型时用 created 和 modified；未指定文件种类时 glob 为 ["**/*"]，is_dir 为 false
- 用户说替换/覆盖/只要这些时 mode=replace，否则 append
"""


def _unique_name(base: str, taken: set[str]) -> str:
    slug = sanitize_id(base or "rule")[:48]
    if slug not in taken:
        return slug
    index = 2
    while f"{slug}-{index}" in taken:
        index += 1
    return f"{slug}-{index}"


def try_parse_structured_rules(text: str) -> list[dict[str, Any]] | None:
    stripped = text.strip()
    if not stripped:
        return None
    raw: Any = None
    if stripped[:1] in {"{", "["}:
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            raw = None
    if raw is None and any(token in stripped for token in ("name:", "when:", "then:", "rules:")):
        try:
            import yaml

            raw = yaml.safe_load(stripped)
        except Exception:  # noqa: BLE001
            raw = None
    if raw is None:
        return None
    if isinstance(raw, list):
        rules = raw
    elif isinstance(raw, dict) and isinstance(raw.get("rules"), list):
        rules = raw["rules"]
    elif isinstance(raw, dict) and "name" in raw and "then" in raw:
        rules = [raw]
    else:
        return None
    dummy = {"name": "preview", "watch": {"path": "."}, "rules": rules}
    parse_config_dict(dummy)
    if not isinstance(rules, list) or not rules:
        raise ConfigError("结构化文本里没有规则")
    return [item for item in rules if isinstance(item, dict)]


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.S)
    if fenced:
        stripped = fenced.group(1)
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(stripped[start : end + 1])
        if isinstance(data, dict):
            return data
    raise ConfigError("LLM 输出不是 JSON 对象")


def _normalize_generated(
    payload: dict[str, Any],
    *,
    existing_names: list[str],
    mode: str | None,
) -> dict[str, Any]:
    rules_raw = payload.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ConfigError("LLM 没有返回规则")
    resolved_mode = mode or str(payload.get("mode") or "append")
    if resolved_mode not in {"append", "replace"}:
        resolved_mode = "append"
    taken = set(existing_names)
    rules: list[dict[str, Any]] = []
    for item in rules_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "rule")
        unique = _unique_name(name, taken) if resolved_mode != "replace" else sanitize_id(name)
        taken.add(unique)
        copied = dict(item)
        copied["name"] = unique
        rules.append(copied)
    if not rules:
        raise ConfigError("LLM 没有返回有效规则")
    parse_config_dict({"name": "preview", "watch": {"path": "."}, "rules": rules})
    notes = payload.get("notes") if isinstance(payload.get("notes"), list) else []
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    return {
        "ok": True,
        "mode": resolved_mode,
        "rules": rules,
        "notes": [str(item) for item in notes],
        "warnings": [str(item) for item in warnings],
    }


def rules_from_text(
    text: str,
    *,
    existing_names: list[str] | None = None,
    mode: str | None = None,
    complete: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    stripped = (text or "").strip()
    if not stripped:
        return {"ok": False, "error": "empty_text", "message": "请输入规则描述"}
    taken = list(existing_names or [])
    try:
        structured = try_parse_structured_rules(stripped)
    except ConfigError as exc:
        return {"ok": False, "error": "bad_config", "message": str(exc)}
    if structured is not None:
        dummy = {"mode": mode or "append", "notes": ["已把输入解析为 YAML/JSON 规则"], "warnings": [], "rules": structured}
        try:
            return _normalize_generated(dummy, existing_names=taken, mode=mode or "append")
        except ConfigError as exc:
            return {"ok": False, "error": "bad_config", "message": str(exc)}

    names = "、".join(taken) if taken else "（无）"
    user = f"已有规则名：{names}\n用户指定 mode：{mode or '未指定'}\n用户描述：\n{stripped}"
    complete_fn = complete or chat_complete
    try:
        raw = complete_fn(SYSTEM_PROMPT, user)
        payload = extract_json_object(raw)
        result = _normalize_generated(payload, existing_names=taken, mode=mode)
        result["notes"] = ["由 LLM 生成", *result["notes"]]
        return result
    except LlmError as exc:
        return {"ok": False, "error": exc.error, "message": exc.message}
    except (ConfigError, json.JSONDecodeError, ValueError) as exc:
        return {"ok": False, "error": "bad_config", "message": f"LLM 输出无法校验：{exc}"}


def merge_rules(
    existing: list[dict[str, Any]],
    generated: list[dict[str, Any]],
    mode: str,
) -> list[dict[str, Any]]:
    if mode == "replace":
        return list(generated)
    by_name = {str(item.get("name")): index for index, item in enumerate(existing)}
    merged = list(existing)
    for rule in generated:
        name = str(rule.get("name"))
        if name in by_name:
            merged[by_name[name]] = rule
        else:
            merged.append(rule)
    return merged
