from __future__ import annotations

import shutil
import subprocess
from typing import Any

from filewatch.agent.sandbox import check_shell_command
from filewatch.agent.types import ToolContext, ToolResult, ToolSpec


def execute_powershell(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolResult(ok=False, error="bad_args", message="command 必须是非空字符串")
    reason = check_shell_command(command, ctx.workspace, ctx.protected_roots)
    if reason:
        return ToolResult(ok=False, error="sandbox_denied", message=reason)
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if not exe:
        return ToolResult(
            ok=False,
            error="powershell_not_found",
            message="未找到 PowerShell（pwsh 或 powershell）",
        )
    timeout = float(args.get("timeout_seconds") or ctx.shell_timeout)
    try:
        completed = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=str(ctx.workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, error="timeout", message=f"PowerShell 超时（{timeout}s）")
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


def build_powershell_tool() -> ToolSpec:
    return ToolSpec(
        name="PowerShell",
        description="在工作区 cwd 下执行 PowerShell 命令。不可删除工作区或 filewatch 自身。不可并行。",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "PowerShell 命令"},
                "timeout_seconds": {"type": "number", "description": "超时秒数，默认 60"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        parallel=False,
        execute=execute_powershell,
    )
