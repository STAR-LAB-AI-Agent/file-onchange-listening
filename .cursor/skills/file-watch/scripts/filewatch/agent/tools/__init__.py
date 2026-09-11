from __future__ import annotations

from filewatch.agent.registry import ToolRegistry
from filewatch.agent.tools.bash import build_bash_tool
from filewatch.agent.tools.glob_tool import build_glob_tool
from filewatch.agent.tools.grep import build_grep_tool
from filewatch.agent.tools.powershell import build_powershell_tool
from filewatch.agent.tools.read import build_read_tool
from filewatch.agent.tools.write import build_write_tool


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for builder in (
        build_read_tool,
        build_glob_tool,
        build_grep_tool,
        build_write_tool,
        build_bash_tool,
        build_powershell_tool,
    ):
        registry.register(builder())
    return registry
