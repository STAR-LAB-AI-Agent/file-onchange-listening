from __future__ import annotations

import json
from pathlib import Path

from filewatch.agent.registry import ToolRegistry
from filewatch.agent.sandbox import check_shell_command, default_protected_roots, resolve_in_workspace
from filewatch.agent.tools import build_default_registry
from filewatch.agent.types import ToolCall, ToolContext, ToolResult, ToolSpec


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        workspace=tmp_path,
        job_id="job_test",
        watch_id="w1",
        protected_roots=default_protected_roots(tmp_path),
    )


def test_read_and_write_and_escape(tmp_path: Path) -> None:
    registry = build_default_registry()
    ctx = _ctx(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    read = registry.get("Read")
    assert read is not None
    ok = read.execute({"path": "a.txt"}, ctx)
    assert ok.ok
    assert ok.data["content"] == "hello"

    bad = read.execute({"path": "../outside.txt"}, ctx)
    assert not bad.ok
    assert bad.error == "path_escape"

    write = registry.get("Write")
    assert write is not None
    suppressed: list[str] = []
    ctx.suppress = lambda p, ttl: suppressed.append(p)
    w = write.execute({"path": "out/b.txt", "content": "world"}, ctx)
    assert w.ok
    assert (tmp_path / "out" / "b.txt").read_text(encoding="utf-8") == "world"
    assert suppressed


def test_glob_and_grep(tmp_path: Path) -> None:
    registry = build_default_registry()
    ctx = _ctx(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("# A\nfoo", encoding="utf-8")
    (tmp_path / "docs" / "b.txt").write_text("bar", encoding="utf-8")
    (tmp_path / "root.md").write_text("baz", encoding="utf-8")

    glob = registry.get("Glob")
    assert glob is not None
    g = glob.execute({"pattern": "docs/**/*.md"}, ctx)
    assert g.ok
    assert g.data["matches"] == ["docs/a.md"]

    grep = registry.get("Grep")
    assert grep is not None
    r = grep.execute({"pattern": "foo", "glob": "**/*.md"}, ctx)
    assert r.ok
    assert any(m["path"] == "docs/a.md" for m in r.data["matches"])


def test_write_not_parallel_in_dispatch(tmp_path: Path) -> None:
    registry = ToolRegistry()
    order: list[str] = []

    def make(name: str, parallel: bool) -> ToolSpec:
        def execute(args: dict, ctx: ToolContext) -> ToolResult:
            order.append(name)
            return ToolResult(ok=True, data={"name": name})

        return ToolSpec(
            name=name,
            description=name,
            parameters={"type": "object", "properties": {}},
            parallel=parallel,
            execute=execute,
        )

    registry.register(make("Read", True))
    registry.register(make("Write", False))
    ctx = _ctx(tmp_path)
    records = registry.dispatch(
        [
            ToolCall(id="1", name="Read", arguments={}),
            ToolCall(id="2", name="Read", arguments={}),
            ToolCall(id="3", name="Write", arguments={}),
            ToolCall(id="4", name="Read", arguments={}),
        ],
        ctx,
    )
    assert len(records) == 4
    assert order.index("Write") >= 0
    assert all(r.result.ok for r in records)


def test_shell_sandbox_denies_delete_workspace(tmp_path: Path) -> None:
    protected = default_protected_roots(tmp_path)
    reason = check_shell_command(f'rm -rf "{tmp_path}"', tmp_path, protected)
    assert reason is not None
    assert "沙箱拒绝" in reason

    reason2 = check_shell_command("Remove-Item -Recurse -Force .", tmp_path, protected)
    assert reason2 is not None

    ok = check_shell_command("echo hello", tmp_path, protected)
    assert ok is None


def test_resolve_in_workspace(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    path = resolve_in_workspace(tmp_path, "sub/x.txt")
    assert path == (tmp_path / "sub" / "x.txt").resolve()
    try:
        resolve_in_workspace(tmp_path, "../../etc/passwd")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "超出工作区" in str(exc)


def test_powershell_sandbox_via_tool(tmp_path: Path) -> None:
    registry = build_default_registry()
    ctx = _ctx(tmp_path)
    ps = registry.get("PowerShell")
    assert ps is not None
    denied = ps.execute({"command": f'Remove-Item -Recurse -Force "{tmp_path}"'}, ctx)
    assert not denied.ok
    assert denied.error == "sandbox_denied"
