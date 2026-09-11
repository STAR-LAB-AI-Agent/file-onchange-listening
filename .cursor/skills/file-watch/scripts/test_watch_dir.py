"""在指定目录创建多种文件，验证 filewatch 的监听与规则命中。

用法：
  python scripts/test_watch_dir.py
  python scripts/test_watch_dir.py --path D:/data/inbox
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from filewatch.config import parse_config_dict
from filewatch.runtime import WatchRuntime
from filewatch.store import WatchStore

PREFIX = "fw_probe_"


def _name(path: str | Path) -> str:
    return Path(path).name.lower()


def _has_file(items: list[dict], name: str, types: set[str] | None = None) -> bool:
    want = name.lower()
    for item in items:
        if _name(item.get("path", "")) != want:
            continue
        if types is None or item.get("type") in types:
            return True
    return False


def _collect(store: WatchStore, stream: str, since: int, timeout: float) -> tuple[list[dict], int]:
    deadline = time.monotonic() + timeout
    seen: list[dict] = []
    cursor = since
    while time.monotonic() < deadline:
        items, cursor, timed_out = store.wait(stream, cursor, timeout=0.2, limit=100)
        seen.extend(items)
        if not timed_out:
            continue
        if seen:
            extra, cursor, _ = store.wait(stream, cursor, timeout=0.15, limit=100)
            seen.extend(extra)
            break
    return seen, cursor


def _cleanup(watch_path: Path) -> None:
    for child in watch_path.glob(f"{PREFIX}*"):
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def run_probe(watch_path: Path, *, timeout: float, keep: bool) -> dict:
    watch_path.mkdir(parents=True, exist_ok=True)
    _cleanup(watch_path)
    home = watch_path.parent / ".filewatch-probe-state"
    if home.exists():
        shutil.rmtree(home, ignore_errors=True)
    os.environ["FILEWATCH_HOME"] = str(home)

    nested = watch_path / f"{PREFIX}nested"
    git_dir = watch_path / f"{PREFIX}repo" / ".git"
    nested.mkdir(parents=True, exist_ok=True)
    git_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "txt": watch_path / f"{PREFIX}hello.txt",
        "md": watch_path / f"{PREFIX}notes.md",
        "json": nested / "data.json",
        "py": watch_path / f"{PREFIX}app.py",
        "tmp": watch_path / f"{PREFIX}ignore.tmp",
        "git": git_dir / "HEAD",
    }

    config = parse_config_dict(
        {
            "name": "probe",
            "watch": {"path": str(watch_path), "debounce_ms": 150, "recursive": True},
            "rules": [
                {
                    "name": "markdown",
                    "when": {"types": ["created", "modified"], "glob": "**/*.md", "is_dir": False},
                    "then": [{"notify": {"title": "md", "message": "{{filename}}"}}],
                },
                {
                    "name": "python",
                    "when": {"types": ["created"], "glob": "**/*.py", "is_dir": False},
                    "then": [{"notify": {"title": "py", "message": "{{filename}}"}}],
                },
            ],
        }
    )
    store = WatchStore("probe", root=home / "watchers")
    runtime = WatchRuntime(config, store)
    runtime.start()
    time.sleep(0.4)

    checks: list[dict] = []
    try:
        files["txt"].write_text("hello", encoding="utf-8")
        files["md"].write_text("# notes", encoding="utf-8")
        files["json"].write_text('{"ok": true}', encoding="utf-8")
        files["py"].write_text("print(1)\n", encoding="utf-8")
        files["tmp"].write_text("tmp", encoding="utf-8")
        files["git"].write_text("ref: refs/heads/main\n", encoding="utf-8")
        created, cursor = _collect(store, "events", 0, timeout)

        files["txt"].write_text("hello world", encoding="utf-8")
        modified, cursor = _collect(store, "events", cursor, timeout)

        moved = watch_path / f"{PREFIX}notes.moved.md"
        files["md"].rename(moved)
        renamed, cursor = _collect(store, "events", cursor, timeout)

        files["json"].unlink()
        deleted, cursor = _collect(store, "events", cursor, timeout)

        jobs, _ = _collect(store, "jobs", 0, timeout)
        events = created + modified + renamed + deleted

        checks = [
            {"name": "新建 txt", "ok": _has_file(created, files["txt"].name, {"created", "modified"})},
            {"name": "新建 md", "ok": _has_file(created, files["md"].name, {"created", "modified"})},
            {"name": "新建嵌套 json", "ok": _has_file(created, files["json"].name, {"created", "modified"})},
            {"name": "新建 py", "ok": _has_file(created, files["py"].name, {"created", "modified"})},
            {"name": "忽略 tmp", "ok": not _has_file(events, files["tmp"].name)},
            {"name": "忽略 .git", "ok": not _has_file(events, "head")},
            {"name": "修改 txt", "ok": _has_file(modified, files["txt"].name, {"modified", "created"})},
            {"name": "移动 md", "ok": _has_file(renamed, moved.name, {"moved", "created", "deleted"})},
            {"name": "删除 json", "ok": _has_file(deleted, files["json"].name, {"deleted", "modified"})},
            {
                "name": "markdown 规则通知",
                "ok": any(job.get("rule") == "markdown" and job.get("status") == "ok" for job in jobs),
            },
            {
                "name": "python 规则通知",
                "ok": any(job.get("rule") == "python" and job.get("status") == "ok" for job in jobs),
            },
        ]
        return {
            "ok": all(item["ok"] for item in checks),
            "path": str(watch_path),
            "checks": checks,
            "events": events,
            "jobs": jobs,
        }
    finally:
        runtime.stop()
        if not keep:
            _cleanup(watch_path)
            if home.exists():
                shutil.rmtree(home, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在指定目录创建多种文件，验证 filewatch 监听效果。")
    parser.add_argument(
        "--path",
        default=str(Path(os.environ.get("TEMP", "/tmp")) / "filewatch-probe"),
        help="要创建文件并监听的目录",
    )
    parser.add_argument("--timeout", type=float, default=6.0, help="每批变更后的等待秒数")
    parser.add_argument("--keep", action="store_true", help="结束后保留探测文件和状态目录")
    parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")
    ns = parser.parse_args(argv)
    result = run_probe(Path(ns.path).expanduser().resolve(), timeout=ns.timeout, keep=ns.keep)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if ns.pretty else None, default=str)
    sys.stdout.write("\n")
    if not result["ok"]:
        failed = [item["name"] for item in result["checks"] if not item["ok"]]
        print(f"失败：{', '.join(failed)}", file=sys.stderr)
        return 1
    print("全部检查通过", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
