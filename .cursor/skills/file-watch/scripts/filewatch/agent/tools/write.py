from __future__ import annotations

from typing import Any

from filewatch.agent.sandbox import resolve_in_workspace
from filewatch.agent.types import ToolContext, ToolResult, ToolSpec
from filewatch.paths import to_posix

_DEFAULT_SUPPRESS_TTL = 2.0


def execute_write(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path_str = args.get("path")
    content = args.get("content")
    if not isinstance(path_str, str) or not path_str.strip():
        return ToolResult(ok=False, error="bad_args", message="path 必须是非空字符串")
    if not isinstance(content, str):
        return ToolResult(ok=False, error="bad_args", message="content 必须是字符串")
    try:
        path = resolve_in_workspace(ctx.workspace, path_str)
    except ValueError as exc:
        return ToolResult(ok=False, error="path_escape", message=str(exc))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return ToolResult(ok=False, error="write_failed", message=f"写入失败：{exc}")
    if ctx.suppress is not None:
        try:
            ctx.suppress(str(path), _DEFAULT_SUPPRESS_TTL)
        except Exception:  # noqa: BLE001
            pass
    try:
        rel = to_posix(path.relative_to(ctx.workspace.resolve()))
    except ValueError:
        rel = to_posix(path)
    return ToolResult(ok=True, data={"path": rel, "bytes": len(content.encode("utf-8"))})


def build_write_tool() -> ToolSpec:
    return ToolSpec(
        name="Write",
        description="向工作区内写入文件（覆盖）。不可并行。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对工作区的文件路径"},
                "content": {"type": "string", "description": "要写入的完整文本"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        parallel=False,
        execute=execute_write,
    )
