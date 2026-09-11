#!/usr/bin/env python3
"""把未构建的 file-watch skill 先构建前端，再打成可安装 zip。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent
SKILL_NAME = "file-watch"

SKIP_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".turbo",
    ".venv",
    ".vite",
    "__pycache__",
    "dist",
    "node_modules",
    "venv",
}
SKIP_FILE_NAMES = {".ds_store", "thumbs.db"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log"}


class PackError(Exception):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error
        self.message = message


def _version() -> str:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from filewatch import __version__

    return __version__


def _emit(payload: dict[str, Any], *, pretty: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None), flush=True)


def _should_skip(path: Path, root: Path, *, include_web_src: bool) -> bool:
    relative = path.relative_to(root)
    parts = relative.parts
    if any(part in SKIP_DIR_NAMES for part in parts):
        return True
    if not include_web_src and parts and parts[0] == "web":
        return True
    if path.is_dir():
        return False
    name = path.name.lower()
    if name in SKIP_FILE_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
        return True
    if name.endswith(".zip"):
        return True
    return False


def iter_skill_files(root: Path, *, include_web_src: bool = True) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        relative = current.relative_to(root)
        parts = relative.parts
        if not include_web_src and parts[:1] == ("web",):
            dirnames[:] = []
            continue
        if any(part in SKIP_DIR_NAMES for part in parts):
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        if not include_web_src:
            dirnames[:] = [name for name in dirnames if name != "web"]
        for name in sorted(filenames):
            path = current / name
            if _should_skip(path, root, include_web_src=include_web_src):
                continue
            yield path


def webui_ready(root: Path) -> bool:
    index = root / "scripts" / "filewatch" / "webui" / "index.html"
    assets = root / "scripts" / "filewatch" / "webui" / "assets"
    if not index.is_file():
        return False
    if not assets.is_dir():
        return False
    return any(assets.iterdir())


def _npm_cmd() -> str:
    found = shutil.which("npm") or shutil.which("npm.cmd")
    if not found:
        raise PackError("npm_missing", "找不到 npm，无法构建前端（可先安装 Node.js，或加 --skip-build）")
    return found


def build_web(root: Path) -> None:
    web = root / "web"
    if not (web / "package.json").is_file():
        raise PackError("not_found", f"找不到前端源码：{web / 'package.json'}")
    npm = _npm_cmd()
    try:
        subprocess.run([npm, "install"], cwd=web, check=True)
        subprocess.run([npm, "run", "build"], cwd=web, check=True)
    except subprocess.CalledProcessError as exc:
        raise PackError("build_failed", f"前端构建失败（退出码 {exc.returncode}）") from exc
    if not webui_ready(root):
        raise PackError("build_failed", "构建结束但 scripts/filewatch/webui/ 缺少页面文件")


def write_zip(root: Path, output: Path, files: Iterable[Path]) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{SKILL_NAME}/{path.relative_to(root).as_posix()}")
            count += 1
    return count


def pack(
    *,
    root: Path | None = None,
    output: Path | None = None,
    skip_build: bool = False,
    include_web_src: bool = True,
) -> dict[str, Any]:
    root = (root or SKILL_ROOT).resolve()
    if not (root / "SKILL.md").is_file():
        raise PackError("not_found", f"不是 skill 根目录（缺少 SKILL.md）：{root}")
    version = _version()
    built = False
    if skip_build:
        if not webui_ready(root):
            raise PackError("not_built", "尚未构建前端，请去掉 --skip-build，或先在 web/ 执行 npm run build")
    else:
        build_web(root)
        built = True
    dest = output or (root / "dist" / f"{SKILL_NAME}-{version}.zip")
    dest = dest.resolve()
    files = list(iter_skill_files(root, include_web_src=include_web_src))
    if dest.is_relative_to(root):
        files = [path for path in files if path.resolve() != dest]
    count = write_zip(root, dest, files)
    return {
        "ok": True,
        "path": str(dest),
        "version": version,
        "files": count,
        "bytes": dest.stat().st_size,
        "built": built,
        "include_web_src": include_web_src,
        "message": f"已打包 {count} 个文件到 {dest}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建前端并打包 file-watch skill")
    parser.add_argument("--output", help="zip 输出路径")
    parser.add_argument("--skip-build", action="store_true", help="跳过 npm 构建，使用已有 webui")
    parser.add_argument("--no-web-src", action="store_true", help="不打进 web/ 前端源码")
    parser.add_argument("--pretty", action="store_true", help="JSON 缩进")
    args = parser.parse_args(argv)
    pretty = bool(args.pretty)
    try:
        payload = pack(
            output=Path(args.output) if args.output else None,
            skip_build=bool(args.skip_build),
            include_web_src=not bool(args.no_web_src),
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
