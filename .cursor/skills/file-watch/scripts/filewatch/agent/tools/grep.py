from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from filewatch.agent.types import ToolContext, ToolResult, ToolSpec
from filewatch.matching import glob_match
from filewatch.paths import to_posix

_MAX_MATCHES = 200
_MAX_LINE = 500


def execute_grep(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return ToolResult(ok=False, error="bad_args", message="pattern 必须是非空字符串")
    glob_pat = args.get("glob", "**/*")
    if not isinstance(glob_pat, str) or not glob_pat.strip():
        return ToolResult(ok=False, error="bad_args", message="glob 必须是非空字符串")
    case_insensitive = bool(args.get("ignore_case", False))
    try:
        regex = re.compile(pattern, re.IGNORECASE if case_insensitive else 0)
    except re.error as exc:
        return ToolResult(ok=False, error="bad_regex", message=f"正则无效：{exc}")
    root = ctx.workspace.resolve()
    hits: list[dict[str, Any]] = []
    files_scanned = 0
    try:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                rel = to_posix(path.relative_to(root))
            except ValueError:
                continue
            if not glob_match(rel, glob_pat.strip(), ignore_case=True):
                continue
            files_scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(
                        {
                            "path": rel,
                            "line": line_no,
                            "text": line[:_MAX_LINE],
                        }
                    )
                    if len(hits) >= _MAX_MATCHES:
                        return ToolResult(
                            ok=True,
                            data={
                                "matches": hits,
                                "files_scanned": files_scanned,
                                "truncated": True,
                            },
                        )
    except OSError as exc:
        return ToolResult(ok=False, error="grep_failed", message=f"搜索失败：{exc}")
    return ToolResult(
        ok=True,
        data={"matches": hits, "files_scanned": files_scanned, "truncated": False},
    )


def build_grep_tool() -> ToolSpec:
    return ToolSpec(
        name="Grep",
        description="在工作区内按正则搜索文件内容，可用 glob 限定文件范围。",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "正则表达式"},
                "glob": {
                    "type": "string",
                    "description": "文件 glob，默认 **/*",
                },
                "ignore_case": {
                    "type": "boolean",
                    "description": "是否忽略大小写",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        parallel=True,
        execute=execute_grep,
    )
