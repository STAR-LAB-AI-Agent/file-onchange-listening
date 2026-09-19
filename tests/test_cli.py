from __future__ import annotations

import json
import os
from pathlib import Path

from filewatch.cli import main
from filewatch.config import config_from_path, config_to_dict
from filewatch.store import WatchStore


def _run(home: Path, argv: list[str]) -> tuple[int, dict]:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["--home", str(home), "--pretty", *argv])
    text = buf.getvalue().strip()
    payload = json.loads(text) if text else {}
    return code, payload


def _seed(home: Path, watch_id: str, folder: Path) -> WatchStore:
    os.environ["FILEWATCH_HOME"] = str(home)
    store = WatchStore(watch_id)
    store.ensure()
    config = config_from_path(str(folder), name=watch_id)
    store.config_path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False), encoding="utf-8")
    return store


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
    code, payload = _run(
        tmp_path / "home",
        ["test-rule", "--config", str(tmp_path / "watch.yaml"), "--path", str(target), "--type", "deleted"],
    )
    assert code == 0
    assert payload["matched"] == []


def test_init_exists_requires_force(tmp_path: Path) -> None:
    target = tmp_path / "watch.yaml"
    target.write_text("existing", encoding="utf-8")
    code, payload = _run(tmp_path / "home", ["init", "--output", str(target)])
    assert code == 1
    assert payload["error"] == "exists"
    code, payload = _run(tmp_path / "home", ["init", "--output", str(target), "--force"])
    assert code == 0
    assert "rules:" in target.read_text(encoding="utf-8")


def test_reload_without_daemon(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    cfg = tmp_path / "watch.yaml"
    cfg.write_text(
        f"name: demo\nwatch:\n  path: {inbox.as_posix()}\nrules:\n"
        "  - name: any\n    when:\n      types: [created]\n      glob: '**/*'\n"
        "    then:\n      - notify:\n          message: '{{path}}'\n",
        encoding="utf-8",
    )
    code, payload = _run(tmp_path / "home", ["reload", "--config", str(cfg), "--id", "demo"])
    assert code == 1
    assert payload["error"] == "not_running"


def test_drain_missing_watcher(tmp_path: Path) -> None:
    code, payload = _run(tmp_path / "home", ["drain", "--id", "nope"])
    assert code == 0
    assert payload["timed_out"] is True
    assert payload["items"] == []


def test_list_wait_ack_status_and_ambiguous(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("FILEWATCH_HOME", str(home))
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    store = _seed(home, "alpha", alpha)
    store.append("events", {"id": "evt_1", "type": "created", "path": str(alpha / "a.txt")})
    _seed(home, "beta", beta)

    code, payload = _run(home, ["list"])
    assert code == 0
    assert {item["watch_id"] for item in payload["watchers"]} == {"alpha", "beta"}

    code, payload = _run(home, ["wait", "--timeout", "0"])
    assert code == 1
    assert payload["error"] == "ambiguous_watch"

    code, payload = _run(home, ["wait", "--id", "alpha", "--timeout", "0", "--stream", "events"])
    assert code == 0
    assert payload["count"] == 1
    cursor = payload["cursor"]
    code, payload = _run(home, ["ack", "--id", "alpha", "--stream", "events", "--cursor", str(cursor)])
    assert code == 0
    assert payload["cursors"]["events"] == cursor
    code, payload = _run(home, ["ack", "--id", "alpha", "--stream", "events", "--cursor", "0"])
    assert code == 1
    assert payload["error"] == "bad_cursor"

    code, payload = _run(home, ["status", "--id", "alpha"])
    assert code == 0
    assert payload["watch_id"] == "alpha"
    assert payload["event_count"] == 1

    code, payload = _run(home, ["stop", "--id", "alpha"])
    assert code == 0
    assert payload["ok"] is True
    assert payload["running"] is False


def test_start_missing_path_and_already_running(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("FILEWATCH_HOME", str(home))
    code, payload = _run(home, ["start", "--path", str(tmp_path / "missing")])
    assert code == 1
    assert payload["error"] == "not_found"

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    store = _seed(home, "inbox", inbox)
    store.write_pid(os.getpid())
    code, payload = _run(home, ["start", "--path", str(inbox), "--id", "inbox"])
    assert code == 0
    assert payload["already_running"] is True
    assert payload["applied"] is False


def test_no_watchers_requires_id(tmp_path: Path) -> None:
    code, payload = _run(tmp_path / "home", ["status"])
    assert code == 1
    assert payload["error"] == "no_watchers"
