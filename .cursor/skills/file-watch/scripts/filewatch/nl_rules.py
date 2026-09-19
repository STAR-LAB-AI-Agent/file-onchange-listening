from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from filewatch.config import ConfigError, parse_config_dict
from filewatch.llm import LlmError, chat_complete
from filewatch.paths import sanitize_id

RULE_JSON_SHAPE = """{
  "name":"小写短横线英文id","enabled":true,"exclude":false,
  "when":{"types":["created"],"glob":["**/*.md"],"regex":null,"is_dir":false,"min_size_bytes":null,"cooldown_seconds":0,"active":null},
  "then":[{"notify":{"title":"...","message":"{{type}}: {{path}}","webhook":null,"mailbox":true,"dingtalk":null}}]
}"""

FIELD_CONSTRAINTS = """- when.types 只能是 created / modified / deleted / moved
- 递归 glob 写 **/*.ext，不要只写 *.ext
- 用户指定生效时段时写 when.active：{"start":"09:00","end":"18:00","days":["mon","tue","wed","thu","fri"]}。未指定则 active 为 null（一直生效）。days 用 mon–sun；结束早于开始表示跨天。不要写时区。
- 用户说不监听/排除/忽略某类文件（反向规则）时：exclude=true，then 必须是 []，when.glob 或 regex 必填（如 ["**/*.log"]）。未指定事件类型时 types 用全部四种。不要写 notify/agent。默认仍监听全部文件，只有反向规则命中的路径才不入账。
- 用户没说任务要求/启动智能体/处理文件时，正向规则 then 只含 notify
- 用户提到钉钉/群机器人时，notify.dingtalk 设为 true（用设置页默认渠道）；指定了渠道名或 id 则写 {"channel":"id"}。不要把 webhook/secret 写进规则
- 文件变化的钉钉是按分钟汇总推送；若同时有 builtin 智能体，完成后会立刻把最后一轮回复推到同一渠道，不要改成即时 webhook
- 用户说了要做什么（重写、处理、启动智能体、按格式改写等）时，then 追加 agent：{"agent":{"runner":"builtin","prompt":"完整任务要求（可用模板变量）","timeout_seconds":1800,"max_steps":24,"command":null,"cwd":null,"model":null,"dingtalk":null}}
- 用户同时要任务要求和钉钉时，agent.dingtalk 与 notify.dingtalk 用同一渠道引用（true 或 {"channel":"id"}）
- agent.runner 默认 builtin（调用设置页 LLM）；高级用法才用 command（须 command 字符串数组）或 cursor_sdk
- 模板变量只能用 {{path}} {{filename}} {{type}} {{watch_id}} {{ts}} {{old_path}} {{json}} {{rule}}
- 正向规则未指定类型时用 created 和 modified；未指定文件种类时 glob 为 ["**/*"]，is_dir 为 false
- 未指定时段时不要写 active，或写 null"""

SYSTEM_PROMPT = f"""你是 filewatch 规则编译器。把用户口语转成 JSON，只输出一个 JSON 对象，不要 markdown。
格式：
{{"notes":["中文说明"],"warnings":[],"rules":[{RULE_JSON_SHAPE}]}}
约束：
- 只生成要新增的规则，不要修改、删除或替换已有规则
{FIELD_CONSTRAINTS}
"""

EDIT_SYSTEM_PROMPT = f"""你是 filewatch 规则编辑器。根据用户指令修改当前这一条规则，只输出一个 JSON 对象，不要 markdown。
格式：
{{"notes":["中文说明"],"warnings":[],"rule":{RULE_JSON_SHAPE}}}
约束：
- 必须返回完整 rule，只改用户提到的部分，其余字段原样保留
- 不要新增其它规则，也不要删除当前规则；用户说停用则 enabled=false
- 用户说改成不监听/排除时：exclude=true，then 必须是 []
- 用户说改回通知/任务时：exclude=false，并补全 then
{FIELD_CONSTRAINTS}
"""


def _unique_name(base: str, taken: set[str]) -> str:
    slug = sanitize_id(base or "rule")[:48]
    if slug not in taken:
        return slug
    index = 2
    while f"{slug}-{index}" in taken:
        index += 1
    return f"{slug}-{index}"


def _dingtalk_hint() -> str:
    try:
        from filewatch.settings import load_dingtalk_channels

        ding_channels = load_dingtalk_channels()
    except Exception:  # noqa: BLE001
        ding_channels = ()
    if ding_channels:
        listing = "、".join(f"{item.id}（{item.name}）" for item in ding_channels)
        return f"可用钉钉渠道：{listing}。用户说钉钉且未指定渠道时 dingtalk=true。"
    return "尚未配置钉钉渠道；用户说钉钉时仍可写 dingtalk=true，并在 notes 提醒去设置页添加机器人。"


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
    elif isinstance(raw, dict) and isinstance(raw.get("rule"), dict):
        rules = [raw["rule"]]
    elif isinstance(raw, dict) and isinstance(raw.get("rules"), list):
        rules = raw["rules"]
    elif isinstance(raw, dict) and "name" in raw and ("then" in raw or raw.get("exclude")):
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


_NO_RETRY_ERRORS = frozenset({"llm_not_configured", "llm_auth", "empty_text"})
_PREVIOUS_OUTPUT_LIMIT = 4000


def _clip_text(text: str, limit: int = _PREVIOUS_OUTPUT_LIMIT) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "\n…(截断)"


def _retry_user(original_user: str, *, error: str, message: str, previous_output: str) -> str:
    parts = [
        original_user,
        "",
        "上次生成失败，请根据错误修正后重新输出符合约束的 JSON 对象，不要 markdown。",
        f"错误码：{error}",
        f"错误原因：{message}",
    ]
    clipped = _clip_text(previous_output) if previous_output else ""
    if clipped:
        parts.extend(["", "上次模型输出：", clipped])
    return "\n".join(parts)


def _llm_once(
    complete_fn: Callable[[str, str], str],
    system: str,
    user: str,
    normalize: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[dict[str, Any] | None, str, str | None, str | None]:
    try:
        raw = complete_fn(system, user)
    except LlmError as exc:
        return None, "", exc.error, exc.message
    try:
        payload = extract_json_object(raw)
        return normalize(payload), raw, None, None
    except (ConfigError, json.JSONDecodeError, ValueError) as exc:
        return None, raw, "bad_config", f"LLM 输出无法校验：{exc}"


def _complete_with_retry(
    complete_fn: Callable[[str, str], str],
    system: str,
    user: str,
    normalize: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    success_note: str,
) -> dict[str, Any]:
    result, raw, error, message = _llm_once(complete_fn, system, user, normalize)
    if result is not None:
        result["notes"] = [success_note, *result["notes"]]
        return result
    if error in _NO_RETRY_ERRORS:
        return {"ok": False, "error": error, "message": message}
    retry_user = _retry_user(
        user,
        error=error or "bad_config",
        message=message or "未知错误",
        previous_output=raw,
    )
    result, _raw2, error2, message2 = _llm_once(complete_fn, system, retry_user, normalize)
    if result is not None:
        result["notes"] = [success_note, "已根据上次错误重试并修正", *result["notes"]]
        result["retried"] = True
        return result
    return {
        "ok": False,
        "error": error2 or error or "bad_config",
        "message": message2 or message or "LLM 输出无法校验",
        "retried": True,
    }


def _list_notes(payload: dict[str, Any], key: str) -> list[str]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _normalize_generated(
    payload: dict[str, Any],
    *,
    existing_names: list[str],
) -> dict[str, Any]:
    rules_raw = payload.get("rules")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise ConfigError("LLM 没有返回规则")
    taken = set(existing_names)
    rules: list[dict[str, Any]] = []
    for item in rules_raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "rule")
        unique = _unique_name(name, taken)
        taken.add(unique)
        copied = dict(item)
        copied["name"] = unique
        rules.append(copied)
    if not rules:
        raise ConfigError("LLM 没有返回有效规则")
    parse_config_dict({"name": "preview", "watch": {"path": "."}, "rules": rules})
    return {
        "ok": True,
        "mode": "append",
        "rules": rules,
        "notes": _list_notes(payload, "notes"),
        "warnings": _list_notes(payload, "warnings"),
    }


def _normalize_edited_rule(
    payload: dict[str, Any],
    *,
    current: dict[str, Any],
    other_names: list[str],
) -> dict[str, Any]:
    rule_raw = payload.get("rule")
    extra_rules = 0
    if not isinstance(rule_raw, dict):
        rules_raw = payload.get("rules")
        if isinstance(rules_raw, list) and rules_raw and isinstance(rules_raw[0], dict):
            rule_raw = rules_raw[0]
            extra_rules = max(len(rules_raw) - 1, 0)
        else:
            raise ConfigError("LLM 没有返回规则")
    elif isinstance(payload.get("rules"), list):
        extra_rules = max(len(payload["rules"]) - 1, 0)
    copied = dict(rule_raw)
    current_name = str(current.get("name") or "rule")
    requested = str(copied.get("name") or current_name)
    if requested == current_name:
        copied["name"] = current_name
    else:
        copied["name"] = _unique_name(requested, set(other_names))
    parse_config_dict({"name": "preview", "watch": {"path": "."}, "rules": [copied]})
    warnings = _list_notes(payload, "warnings")
    if extra_rules:
        warnings.append("只应用了第一条规则，编辑不会新增其它规则")
    return {
        "ok": True,
        "rule": copied,
        "notes": _list_notes(payload, "notes"),
        "warnings": warnings,
    }


def rules_from_text(
    text: str,
    *,
    existing_names: list[str] | None = None,
    mode: str | None = None,
    complete: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    del mode
    stripped = (text or "").strip()
    if not stripped:
        return {"ok": False, "error": "empty_text", "message": "请输入规则描述"}
    taken = list(existing_names or [])
    try:
        structured = try_parse_structured_rules(stripped)
    except ConfigError as exc:
        return {"ok": False, "error": "bad_config", "message": str(exc)}
    if structured is not None:
        dummy = {"notes": ["已把输入解析为 YAML/JSON 规则"], "warnings": [], "rules": structured}
        try:
            return _normalize_generated(dummy, existing_names=taken)
        except ConfigError as exc:
            return {"ok": False, "error": "bad_config", "message": str(exc)}

    names = "、".join(taken) if taken else "（无）"
    ding_hint = _dingtalk_hint()
    user = f"已有规则名：{names}（不要修改这些规则，只新增）\n{ding_hint}\n用户描述：\n{stripped}"
    complete_fn = complete or chat_complete
    return _complete_with_retry(
        complete_fn,
        SYSTEM_PROMPT,
        user,
        lambda payload: _normalize_generated(payload, existing_names=taken),
        success_note="由 LLM 生成",
    )


def edit_rule_from_text(
    text: str,
    *,
    current: dict[str, Any],
    existing_names: list[str] | None = None,
    complete: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    stripped = (text or "").strip()
    if not stripped:
        return {"ok": False, "error": "empty_text", "message": "请输入修改说明"}
    current_name = str(current.get("name") or "")
    other_names = [name for name in (existing_names or []) if name != current_name]
    try:
        structured = try_parse_structured_rules(stripped)
    except ConfigError as exc:
        return {"ok": False, "error": "bad_config", "message": str(exc)}
    if structured is not None:
        dummy = {
            "notes": ["已把输入解析为 YAML/JSON 规则"],
            "warnings": [],
            "rule": structured[0],
            "rules": structured,
        }
        try:
            return _normalize_edited_rule(dummy, current=current, other_names=other_names)
        except ConfigError as exc:
            return {"ok": False, "error": "bad_config", "message": str(exc)}

    others = "、".join(other_names) if other_names else "（无）"
    ding_hint = _dingtalk_hint()
    user = (
        f"当前规则：\n{json.dumps(current, ensure_ascii=False)}\n"
        f"其它已有规则名：{others}\n{ding_hint}\n用户指令：\n{stripped}"
    )
    complete_fn = complete or chat_complete
    return _complete_with_retry(
        complete_fn,
        EDIT_SYSTEM_PROMPT,
        user,
        lambda payload: _normalize_edited_rule(payload, current=current, other_names=other_names),
        success_note="由 LLM 编辑",
    )


def merge_rules(
    existing: list[dict[str, Any]],
    generated: list[dict[str, Any]],
    mode: str | None = None,
) -> list[dict[str, Any]]:
    del mode
    return [*existing, *generated]
