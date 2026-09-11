from __future__ import annotations

from pathlib import Path
from typing import Any

from filewatch.agent.sandbox import resolve_in_workspace
from filewatch.agent.types import ToolContext, ToolResult, ToolSpec
from filewatch.paths import to_posix

_MAX_CHARS = 200_000
_MAX_FILES = 20


def _read_one(workspace: Path, path_str: str) -> dict[str, Any]:
    try:
        path = resolve_in_workspace(workspace, path_str)
    except ValueError as exc:
        return {"path": path_str, "ok": False, "error": "path_escape", "message": str(exc)}
    if not path.exists():
        return {
            "path": to_posix(path_str),
            "ok": False,
            "error": "not_found",
            "message": f"文件不存在：{path_str}",
        }
    if not path.is_file():
        return {
            "path": to_posix(path_str),
            "ok": False,
            "error": "not_a_file",
            "message": f"不是文件：{path_str}",
        }
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {
                "path": to_posix(path_str),
                "ok": False,
                "error": "read_failed",
                "message": f"读取失败：{exc}",
            }
    except OSError as exc:
        return {
            "path": to_posix(path_str),
            "ok": False,
            "error": "read_failed",
            "message": f"读取失败：{exc}",
        }
    truncated = False
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS]
        truncated = True
    return {
        "path": to_posix(path.relative_to(workspace.resolve())),
        "ok": True,
        "content": text,
        "truncated": truncated,
    }


def execute_read(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    paths: list[str] = []
    if "paths" in args and args["paths"] is not None:
        raw = args["paths"]
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            return ToolResult(ok=False, error="bad_args", message="paths 必须是字符串列表")
        paths = list(raw)
    elif "path" in args and args["path"] is not None:
        if not isinstance(args["path"], str):
            return ToolResult(ok=False, error="bad_args", message="path 必须是字符串")
        paths = [args["path"]]
    else:
        return ToolResult(ok=False, error="bad_args", message="必须提供 path 或 paths")
    if not paths:
        return ToolResult(ok=False, error="bad_args", message="路径列表为空")
    if len(paths) > _MAX_FILES:
        return ToolResult(
            ok=False,
            error="too_many_files",
            message=f"一次最多读取 {_MAX_FILES} 个文件",
        )
    results = [_read_one(ctx.workspace, p) for p in paths]
    all_ok = all(item.get("ok") for item in results)
    if len(results) == 1:
        item = results[0]
        if item.get("ok"):
            return ToolResult(ok=True, data={"path": item["path"], "content": item["content"], "truncated": item["truncated"]})
        return ToolResult(ok=False, error=item.get("error"), message=item.get("message"))
    return ToolResult(ok=all_ok, data={"files": results})


def build_read_tool() -> ToolSpec:
    return ToolSpec(
        name="Read",
        description="读取工作区内一个或多个文件的文本内容。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对工作区的单个文件路径"},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "相对工作区的多个文件路径",
                },
            },
            "additionalProperties": False,
        },
        parallel=True,
        execute=execute_read,
    )
