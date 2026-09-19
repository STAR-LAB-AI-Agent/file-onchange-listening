#!/usr/bin/env python3
"""把 file-watch skill 整理成 nanobot 可用布局，打成 .skill（zip）。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import yaml

import pack_skill
from pack_skill import PackError

SKILL_NAME = pack_skill.SKILL_NAME
SCRIPTS_DIR = pack_skill.SCRIPTS_DIR
SKILL_ROOT = pack_skill.SKILL_ROOT

ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "metadata",
    "always",
    "license",
    "allowed-tools",
}
ALLOWED_RESOURCE_DIRS = {"scripts", "references", "assets"}
SKIP_PACK_SCRIPTS = {"pack_skill.py", "pack_nanobot.py"}
SKIP_ROOT_FILES = {"pack.cmd", "pack.sh", "pack_nanobot.cmd", "pack_nanobot.sh"}

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

NANOBOT_INSTALL = """## 安装（nanobot）

本包给 nanobot 用。把 `.skill` 当 zip 解压到工作区，使路径为 `{workspace}/skills/file-watch/SKILL.md`（也可用 `nanobot skill install` 安装该文件）。

```bash
pip install -r scripts/requirements.txt
```

网页已包含 `scripts/filewatch/webui/`，不必再带 `web/` 源码。`agent.runner: cursor_sdk` 需要 Cursor 与 `CURSOR_API_KEY`；nanobot 里请用 `builtin` 或 `command`。
"""


def _emit(payload: dict[str, Any], *, pretty: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None), flush=True)


def rewrite_skill_md(text: str) -> str:
    match = _FRONTMATTER.match(text)
    if not match:
        raise PackError("invalid_skill", "SKILL.md 缺少 YAML frontmatter")
    raw_fm = match.group(1)
    parsed = yaml.safe_load(raw_fm)
    if not isinstance(parsed, dict):
        raise PackError("invalid_skill", "SKILL.md frontmatter 必须是 YAML 对象")
    metadata = parsed.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    nanobot_meta = metadata.get("nanobot")
    if not isinstance(nanobot_meta, dict):
        nanobot_meta = {}
    nanobot_meta.setdefault("always", False)
    metadata["nanobot"] = nanobot_meta
    parsed["metadata"] = metadata
    frontmatter = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False).strip()
    body = text[match.end() :]
    body = body.replace("pip install -r requirements.txt", "pip install -r scripts/requirements.txt")
    body = body.replace(
        "python .cursor/skills/file-watch/scripts/filewatch_cli.py",
        "python scripts/filewatch_cli.py",
    )
    body = body.replace("examples/watch.yaml", "references/examples/watch.yaml")
    body = re.sub(
        r"下文用 `python scripts/filewatch_cli.py` 表示相对本 skill 根目录。从本仓库调用时等价于：\r?\n\r?\n```bash\r?\npython scripts/filewatch_cli.py\r?\n```",
        "下文用 `python scripts/filewatch_cli.py` 表示相对本 skill 根目录（nanobot 工作区为 `skills/file-watch/`）。",
        body,
        count=1,
    )
    body = re.sub(r"\n## 打包\n.*\Z", "\n" + NANOBOT_INSTALL, body, flags=re.DOTALL)
    return f"---\n{frontmatter}\n---\n{body.lstrip()}" if not body.startswith("\n") else f"---\n{frontmatter}\n---{body}"


def validate_nanobot_skill(skill_path: Path) -> tuple[bool, str]:
    skill_path = skill_path.resolve()
    skill_md = skill_path / "SKILL.md"
    if not skill_md.is_file():
        return False, "SKILL.md not found"
    content = skill_md.read_text(encoding="utf-8")
    match = _FRONTMATTER.match(content)
    if not match:
        return False, "Invalid frontmatter format"
    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return False, f"Invalid YAML in frontmatter: {exc}"
    if not isinstance(frontmatter, dict):
        return False, "Frontmatter must be a YAML dictionary"
    unexpected = sorted(set(frontmatter) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected:
        allowed = ", ".join(sorted(ALLOWED_FRONTMATTER_KEYS))
        return False, f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(unexpected)}. Allowed properties are: {allowed}"
    name = frontmatter.get("name")
    if not isinstance(name, str):
        return False, "Missing 'name' in frontmatter"
    name = name.strip()
    if not _NAME_RE.fullmatch(name):
        return False, f"Name '{name}' should be hyphen-case (lowercase letters, digits, and single hyphens only)"
    if len(name) > 64:
        return False, f"Name is too long ({len(name)} characters). Maximum is 64 characters."
    if name != skill_path.name:
        return False, f"Skill name '{name}' must match directory name '{skill_path.name}'"
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        return False, "Missing 'description' in frontmatter"
    trimmed = description.strip()
    if "<" in trimmed or ">" in trimmed:
        return False, "Description cannot contain angle brackets (< or >)"
    if len(trimmed) > 1024:
        return False, f"Description is too long ({len(trimmed)} characters). Maximum is 1024 characters."
    always = frontmatter.get("always")
    if always is not None and not isinstance(always, bool):
        return False, f"'always' must be a boolean, got {type(always).__name__}"
    for child in skill_path.iterdir():
        if child.is_symlink():
            return False, f"Symlink not allowed: {child.name}"
        if child.name == "SKILL.md":
            continue
        if child.is_dir() and child.name in ALLOWED_RESOURCE_DIRS:
            continue
        return False, (
            f"Unexpected file or directory in skill root: {child.name}. "
            "Only SKILL.md, scripts/, references/, and assets/ are allowed."
        )
    return True, "Skill is valid!"


def _dest_for(relative: Path) -> Path | None:
    parts = relative.parts
    if not parts:
        return None
    if parts == ("SKILL.md",):
        return None
    if parts[0] == "web":
        return None
    if len(parts) == 1 and parts[0] in SKIP_ROOT_FILES:
        return None
    if parts == ("requirements.txt",):
        return Path("scripts") / "requirements.txt"
    if parts[0] == "examples":
        return Path("references").joinpath(*parts)
    if parts[0] == "scripts":
        if len(parts) == 2 and parts[1] in SKIP_PACK_SCRIPTS:
            return None
        return relative
    return None


def stage_nanobot_skill(root: Path, staging: Path) -> int:
    skill_dir = staging / SKILL_NAME
    skill_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in pack_skill.iter_skill_files(root, include_web_src=False):
        if path.is_symlink():
            raise PackError("symlink", f"不允许打包符号链接：{path}")
        dest_rel = _dest_for(path.relative_to(root))
        if dest_rel is None:
            continue
        dest = skill_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        count += 1
    rewritten = rewrite_skill_md((root / "SKILL.md").read_text(encoding="utf-8"))
    (skill_dir / "SKILL.md").write_text(rewritten, encoding="utf-8", newline="\n")
    count += 1
    if not (skill_dir / "scripts" / "requirements.txt").is_file():
        raise PackError("not_found", "缺少 requirements.txt")
    valid, message = validate_nanobot_skill(skill_dir)
    if not valid:
        raise PackError("invalid_skill", message)
    return count


def write_skill_archive(skill_dir: Path, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(skill_dir.rglob("*")):
            if path.is_symlink():
                raise PackError("symlink", f"不允许打包符号链接：{path}")
            if not path.is_file():
                continue
            archive.write(path, f"{SKILL_NAME}/{path.relative_to(skill_dir).as_posix()}")
            count += 1
    return count


def pack(
    *,
    root: Path | None = None,
    output: Path | None = None,
    skip_build: bool = False,
) -> dict[str, Any]:
    root = (root or SKILL_ROOT).resolve()
    if not (root / "SKILL.md").is_file():
        raise PackError("not_found", f"不是 skill 根目录（缺少 SKILL.md）：{root}")
    version = pack_skill._version()
    built = False
    if skip_build:
        if not pack_skill.webui_ready(root):
            raise PackError("not_built", "尚未构建前端，请去掉 --skip-build，或先在 web/ 执行 npm run build")
    else:
        pack_skill.build_web(root)
        built = True
    dest = output or (root / "dist" / f"{SKILL_NAME}-{version}.skill")
    dest = dest.resolve()
    with tempfile.TemporaryDirectory(prefix="filewatch-nanobot-") as tmp:
        staging = Path(tmp)
        staged_files = stage_nanobot_skill(root, staging)
        skill_dir = staging / SKILL_NAME
        archived = write_skill_archive(skill_dir, dest)
    return {
        "ok": True,
        "path": str(dest),
        "version": version,
        "files": archived,
        "staged": staged_files,
        "bytes": dest.stat().st_size,
        "built": built,
        "message": f"已打包 nanobot skill {archived} 个文件到 {dest}；解压到工作区 skills/ 得到 {SKILL_NAME}/",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建前端并打包 nanobot 可用的 file-watch .skill")
    parser.add_argument("--output", help=".skill 输出路径")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm 构建，使用已有 webui")
    parser.add_argument("--pretty", action="store_true", help="JSON 缩进")
    args = parser.parse_args(argv)
    pretty = bool(args.pretty)
    try:
        payload = pack(
            output=Path(args.output) if args.output else None,
            skip_build=bool(args.skip_build),
        )
    except PackError as exc:
        _emit({"ok": False, "error": exc.error, "message": exc.message}, pretty=pretty)
        return 1
    except OSError as exc:
        _emit({"ok": False, "error": "io_error", "message": str(exc)}, pretty=pretty)
        return 1
    _emit(payload, pretty=pretty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
