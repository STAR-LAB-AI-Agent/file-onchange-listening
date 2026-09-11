from __future__ import annotations

import re
from pathlib import Path

from filewatch.paths import state_root, to_posix


def resolve_in_workspace(workspace: Path, rel_or_abs: str) -> Path:
    """解析路径并确保落在工作区内。越界抛 ValueError。"""
    raw = (rel_or_abs or "").strip()
    if not raw:
        raise ValueError("路径为空")
    root = workspace.resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ValueError(f"无法解析路径：{exc}") from exc
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"路径超出工作区：{raw}")
    return resolved


def is_under(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        base = root.resolve()
    except OSError:
        return False
    return resolved == base or base in resolved.parents


def default_protected_roots(workspace: Path) -> tuple[Path, ...]:
    roots: list[Path] = [workspace.resolve(), state_root()]
    # filewatch package / skill directory
    pkg = Path(__file__).resolve().parents[1]  # filewatch/
    skill = Path(__file__).resolve().parents[3]  # file-watch skill root
    roots.append(pkg)
    roots.append(skill)
    # de-dupe while preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for item in roots:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return tuple(out)


_DELETE_PATTERNS = [
    re.compile(r"\brm\b", re.IGNORECASE),
    re.compile(r"\brmdir\b", re.IGNORECASE),
    re.compile(r"\bunlink\b", re.IGNORECASE),
    re.compile(r"\bdel\b", re.IGNORECASE),
    re.compile(r"\berase\b", re.IGNORECASE),
    re.compile(r"\bRemove-Item\b", re.IGNORECASE),
    re.compile(r"\bri\b", re.IGNORECASE),  # PowerShell alias
    re.compile(r"\brd\b", re.IGNORECASE),
]


def shell_delete_targets(command: str) -> list[str]:
    """粗提取删除类命令的目标路径（启发式）。"""
    text = command.strip()
    if not text:
        return []
    targets: list[str] = []
    # PowerShell Remove-Item ... <path>
    for match in re.finditer(
        r"(?:Remove-Item|ri|rd)\b((?:\s+-\w+(?:[:\s]+[^\s\"']+)?)*)\s+([\"'][^\"']+[\"']|[^\s;&|]+)",
        text,
        re.IGNORECASE,
    ):
        targets.append(match.group(2).strip("\"'"))
    # cmd del / erase
    for match in re.finditer(
        r"\b(?:del|erase)\b(?:\s+/[a-zA-Z]+)*\s+([\"'][^\"']+[\"']|[^\s;&|]+)",
        text,
        re.IGNORECASE,
    ):
        targets.append(match.group(1).strip("\"'"))
    # rm / rmdir style
    for match in re.finditer(
        r"\b(?:rm|rmdir|unlink)\b(?:\s+-[a-zA-Z]+)*\s+([\"'][^\"']+[\"']|[^\s;&|]+)",
        text,
        re.IGNORECASE,
    ):
        targets.append(match.group(1).strip("\"'"))
    return [t for t in targets if t and not t.startswith("-")]


def check_shell_command(command: str, workspace: Path, protected: tuple[Path, ...]) -> str | None:
    """若命令不安全，返回中文拒绝原因；否则 None。"""
    text = command.strip()
    if not text:
        return "命令为空"
    has_delete = any(pat.search(text) for pat in _DELETE_PATTERNS)
    if not has_delete:
        return None
    targets = shell_delete_targets(text)
    resolved_targets: list[Path] = []
    for target in targets:
        cleaned = target.strip("\"'`")
        if not cleaned or cleaned.startswith("-"):
            continue
        try:
            if Path(cleaned).is_absolute():
                path = Path(cleaned).resolve()
            else:
                path = (workspace / cleaned).resolve()
        except OSError:
            return f"沙箱拒绝：无法解析删除目标 {cleaned}"
        resolved_targets.append(path)
    if not resolved_targets:
        # 有删除动词但解析不出目标时仍拒绝，避免漏拦（如 Remove-Item -Recurse -Force .）
        # 再试：命令末尾的相对路径 / .
        trailing = re.search(
            r"(?:Remove-Item|ri|rd|del|erase|rm|rmdir)\b.*?\s+([.\"'/\w\\:-]+)\s*$",
            text,
            re.IGNORECASE,
        )
        if trailing:
            cleaned = trailing.group(1).strip("\"'`")
            if cleaned and not cleaned.startswith("-"):
                try:
                    if Path(cleaned).is_absolute():
                        resolved_targets.append(Path(cleaned).resolve())
                    else:
                        resolved_targets.append((workspace / cleaned).resolve())
                except OSError:
                    return f"沙箱拒绝：无法解析删除目标 {cleaned}"
        if not resolved_targets:
            return "沙箱拒绝：删除类命令必须给出明确目标路径，且不得删除工作区或 filewatch 自身"
    for path in resolved_targets:
        for root in protected:
            if is_under(path, root) or path == root.resolve():
                return (
                    f"沙箱拒绝：不允许删除受保护路径 {to_posix(path)} "
                    f"（受保护根：{to_posix(root)}）"
                )
    return None
