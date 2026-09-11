from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from filewatch.config import config_to_dict, parse_config_dict
from filewatch.store import WatchStore
from filewatch.web import serve_http


def _get(url: str) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")
            ctype = response.headers.get("Content-Type", "")
            if "json" in ctype:
                return response.status, json.loads(body)
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def _post(url: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _put(url: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_web_page_lists_seeded_events(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("FILEWATCH_HOME", str(home))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    store = WatchStore("demo")
    store.ensure()
    config = parse_config_dict({"name": "demo", "watch": {"path": str(inbox)}, "rules": []})
    store.config_path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False), encoding="utf-8")
    store.append("events", {"id": "evt_1", "type": "created", "path": str(inbox / "a.txt"), "ts": "2026-01-01T00:00:00Z"})

    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, html = _get(f"http://127.0.0.1:{port}/")
        assert status == 200
        assert isinstance(html, str)
        assert "filewatch" in html.lower()
        match = re.search(r'src="(/assets/[^"]+\.js)"', html)
        assert match, html[:500]
        status, asset = _get(f"http://127.0.0.1:{port}{match.group(1)}")
        assert status == 200
        assert isinstance(asset, str) and len(asset) > 100
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers")
        assert status == 200
        assert payload["watchers"][0]["watch_id"] == "demo"
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers/demo/events?tail=1")
        assert status == 200
        assert payload["items"][0]["id"] == "evt_1"
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers/missing/events")
        assert status == 404
        assert payload["error"] == "not_found"
        status, html = _get(f"http://127.0.0.1:{port}/tasks/demo")
        assert status == 200
        assert isinstance(html, str)
        assert 'id="root"' in html
        assert "filewatch" in html.lower()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_web_start_records_created_file(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("FILEWATCH_HOME", str(home))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    httpd = serve_http("127.0.0.1", 0)
    watch_id = None
    try:
        port = httpd.server_address[1]
        status, payload = _post(f"http://127.0.0.1:{port}/api/watchers/start", {"path": str(inbox)})
        assert status == 200, payload
        assert payload["ok"] is True
        watch_id = payload["watch_id"]
        (inbox / "hello.txt").write_text("hi", encoding="utf-8")
        items = []
        deadline = time.time() + 6
        while time.time() < deadline and not items:
            status, data = _get(f"http://127.0.0.1:{port}/api/watchers/{watch_id}/events?tail=1&limit=50")
            assert status == 200
            items = [item for item in data["items"] if str(item.get("path", "")).endswith("hello.txt")]
            if not items:
                time.sleep(0.2)
        assert items, "web API did not surface the created file event"
    finally:
        if watch_id:
            _post(f"http://127.0.0.1:{port}/api/watchers/{watch_id}/stop", {})
        httpd.shutdown()
        httpd.server_close()


def _seed_watcher(watch_id: str, folder: Path, event: dict) -> WatchStore:
    store = WatchStore(watch_id)
    store.ensure()
    config = parse_config_dict({"name": watch_id, "watch": {"path": str(folder)}, "rules": []})
    store.config_path.write_text(json.dumps(config_to_dict(config), ensure_ascii=False), encoding="utf-8")
    store.append("events", event)
    return store


def test_web_lists_tasks_and_isolates_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    reports = tmp_path / "reports"
    inbox.mkdir()
    reports.mkdir()
    _seed_watcher(
        "inbox",
        inbox,
        {"id": "evt_inbox", "type": "created", "path": str(inbox / "a.txt")},
    )
    _seed_watcher(
        "reports",
        reports,
        {"id": "evt_reports", "type": "modified", "path": str(reports / "b.md")},
    )

    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers")
        assert status == 200
        by_id = {item["watch_id"]: item for item in payload["watchers"]}
        assert set(by_id) == {"inbox", "reports"}
        assert by_id["inbox"]["title"] == "inbox"
        assert by_id["inbox"]["event_count"] == 1
        assert by_id["inbox"]["last_event"]["id"] == "evt_inbox"
        assert by_id["reports"]["last_event"]["id"] == "evt_reports"

        status, data = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/events?tail=1")
        assert status == 200
        assert [item["id"] for item in data["items"]] == ["evt_inbox"]
        status, data = _get(f"http://127.0.0.1:{port}/api/watchers/reports/events?tail=1")
        assert status == 200
        assert [item["id"] for item in data["items"]] == ["evt_reports"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_web_rules_manual_and_natural_language(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _seed_watcher(
        "inbox",
        inbox,
        {"id": "evt_inbox", "type": "created", "path": str(inbox / "a.txt")},
    )
    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, html = _get(f"http://127.0.0.1:{port}/tasks/inbox/rules")
        assert status == 200
        assert isinstance(html, str)
        assert 'id="root"' in html

        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/config")
        assert status == 200
        assert payload["config"]["rules"] == []

        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules/from-text",
            {"text": "新建 markdown 时通知我", "apply": False},
        )
        assert status == 400
        assert payload["error"] == "llm_not_configured"

        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules/from-text",
            {
                "text": "- name: from-yaml\n  when:\n    types: [created]\n    glob: ['**/*.md']\n  then:\n    - notify:\n        title: t\n        message: '{{filename}}'\n",
                "apply": False,
            },
        )
        assert status == 200, payload
        assert payload["rules"][0]["name"] == "from-yaml"
        assert payload["rules"][0]["when"]["glob"] == ["**/*.md"]

        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules",
            {
                "rules": [
                    {
                        "name": "manual",
                        "when": {"types": ["deleted"], "glob": ["**/*.txt"], "is_dir": False},
                        "then": [{"notify": {"title": "删了", "message": "{{path}}"}}],
                    }
                ]
            },
        )
        assert status == 200, payload
        assert payload["rules"] == ["manual"]
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/config")
        assert payload["config"]["rules"][0]["name"] == "manual"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_web_settings_and_llm_from_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _seed_watcher("inbox", inbox, {"id": "evt_inbox", "type": "created", "path": str(inbox / "a.txt")})

    def fake_complete(_system: str, _user: str) -> str:
        return json.dumps(
            {
                "mode": "append",
                "notes": ["llm"],
                "rules": [
                    {
                        "name": "created-md",
                        "when": {"types": ["created"], "glob": ["**/*.md"], "is_dir": False},
                        "then": [{"notify": {"title": "t", "message": "{{filename}}"}}],
                    }
                ],
            }
        )

    monkeypatch.setattr("filewatch.nl_rules.chat_complete", fake_complete)
    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, html = _get(f"http://127.0.0.1:{port}/settings")
        assert status == 200
        assert isinstance(html, str)
        assert 'id="root"' in html
        status, payload = _get(f"http://127.0.0.1:{port}/api/settings")
        assert status == 200
        assert payload["llm"]["api_key_set"] is False
        status, payload = _put(
            f"http://127.0.0.1:{port}/api/settings",
            {"llm": {"api_key": "sk-test-key-9999", "model": "demo", "base_url": "https://example.invalid/v1"}},
        )
        assert status == 200, payload
        assert payload["llm"]["api_key_set"] is True
        assert "sk-test-key-9999" not in json.dumps(payload)
        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules/from-text",
            {"text": "新建 markdown 时通知我", "apply": True},
        )
        assert status == 200, payload
        assert payload["config"]["rules"][0]["when"]["glob"] == ["**/*.md"]
    finally:
        httpd.shutdown()
        httpd.server_close()

