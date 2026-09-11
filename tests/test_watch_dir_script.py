from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".cursor"
    / "skills"
    / "file-watch"
    / "scripts"
    / "test_watch_dir.py"
)


def test_watch_dir_script_creates_mixed_files(tmp_path: Path) -> None:
    target = tmp_path / "inbox"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--path", str(target), "--pretty"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert completed.returncode == 0, completed.stdout + "\n" + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert all(item["ok"] for item in payload["checks"])
