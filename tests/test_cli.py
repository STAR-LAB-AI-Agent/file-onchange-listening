from __future__ import annotations

import json
from pathlib import Path

from filewatch.cli import main


def _run(home: Path, argv: list[str]) -> tuple[int, dict]:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["--home", str(home), "--pretty", *argv])
    text = buf.getvalue().strip()
    payload = json.loads(text) if text else {}
    return code, payload


def test_init_and_test_rule(tmp_path: Path) -> None:
    code, payload = _run(tmp_path / "home", ["init", "--output", str(tmp_path / "watch.yaml")])
    assert code == 0
    assert Path(payload["path"]).exists()
    inbox = tmp_path / "inbox"
    target = inbox / "note.md"
    target.write_text("x", encoding="utf-8")
    yaml_text = (tmp_path / "watch.yaml").read_text(encoding="utf-8")
    yaml_text = yaml_text.replace("path: ./inbox", f"path: {inbox.as_posix()}")
    (tmp_path / "watch.yaml").write_text(yaml_text, encoding="utf-8")
    code, payload = _run(
        tmp_path / "home",
        ["test-rule", "--config", str(tmp_path / "watch.yaml"), "--path", str(target), "--type", "created"],
    )
    assert code == 0
    assert "any-file-change" in payload["matched"]


def test_drain_missing_watcher(tmp_path: Path) -> None:
    code, payload = _run(tmp_path / "home", ["drain", "--id", "nope"])
    assert code == 0
    assert payload["timed_out"] is True
    assert payload["items"] == []
