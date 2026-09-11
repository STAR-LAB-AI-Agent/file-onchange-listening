from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from filewatch.agent.sandbox import check_shell_command
from filewatch.agent.types import ToolContext, ToolResult, ToolSpec


def _find_bash() -> str | None:
    for name in ("bash", "bash.exe"):
        found = shutil.which(name)
        if found:
            return found
    # Common Git Bash locations on Windows
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def execute_bash(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolResult(ok=False, error="bad_args", message="command 必须是非空字符串")
    protected = ctx.protected_roots
    reason = check_shell_command(command, ctx.workspace, protected)
    if reason:
        return ToolResult(ok=False, error="sandbox_denied", message=reason)
    bash = _find_bash()
    if not bash:
        return ToolResult(
            ok=False,
            error="bash_not_found",
            message="未找到 bash（可安装 Git Bash 或确保 bash 在 PATH 中）",
        )
    timeout = float(args.get("timeout_seconds") or ctx.shell_timeout)
    try:
        completed = subprocess.run(
            [bash, "-lc", command],
            cwd=str(ctx.workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, error="timeout", message=f"Bash 超时（{timeout}s）")
    except OSError as exc:
        return ToolResult(ok=False, error="exec_failed", message=f"执行失败：{exc}")
    output = (completed.stdout or "") + (completed.stderr or "")
    if len(output) > 20_000:
        output = output[-20_000:]
    if completed.returncode != 0:
        return ToolResult(
            ok=False,
            error="nonzero_exit",
            message=f"退出码 {completed.returncode}",
            data={"exit_code": completed.returncode, "output": output},
        )
    return ToolResult(ok=True, data={"exit_code": 0, "output": output})


def build_bash_tool() -> ToolSpec:
    return ToolSpec(
        name="Bash",
        description="在工作区 cwd 下执行 bash 命令。不可删除工作区或 filewatch 自身。不可并行。",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "bash 命令"},
                "timeout_seconds": {"type": "number", "description": "超时秒数，默认 60"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        parallel=False,
        execute=execute_bash,
    )
