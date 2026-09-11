from __future__ import annotations

from pathlib import Path
from typing import Any

from filewatch.agent.types import ToolContext, ToolResult, ToolSpec
from filewatch.matching import glob_match
from filewatch.paths import to_posix


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file():
            files.append(path)
    return files


def execute_glob(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip():
        return ToolResult(ok=False, error="bad_args", message="pattern 必须是非空字符串")
    pattern = pattern.strip()
    root = ctx.workspace.resolve()
    ignore_case = True  # Windows-friendly; also fine on POSIX for agent use
    matches: list[str] = []
    try:
        for path in _iter_files(root):
            try:
                rel = to_posix(path.relative_to(root))
            except ValueError:
                continue
            if glob_match(rel, pattern, ignore_case=ignore_case):
                matches.append(rel)
    except OSError as exc:
        return ToolResult(ok=False, error="glob_failed", message=f"列举文件失败：{exc}")
    matches.sort()
    limit = args.get("limit", 500)
    try:
        limit_i = int(limit)
    except (TypeError, ValueError):
        return ToolResult(ok=False, error="bad_args", message="limit 必须是整数")
    truncated = len(matches) > limit_i
    return ToolResult(
        ok=True,
        data={
            "pattern": pattern,
            "matches": matches[:limit_i],
            "count": len(matches),
            "truncated": truncated,
        },
    )


def build_glob_tool() -> ToolSpec:
    return ToolSpec(
        name="Glob",
        description="按相对 posix glob 模式列出工作区内的文件（**/ 可为空前缀）。",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "例如 **/*.md 或 docs/**/*.txt",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少条，默认 500",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        parallel=True,
        execute=execute_glob,
    )
