from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
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


def _patch(url: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="PATCH",
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

        status, data = _patch(
            f"http://127.0.0.1:{port}/api/watchers/inbox",
            {"name": "收件箱"},
        )
        assert status == 200, data
        assert data["ok"] is True
        assert data["title"] == "收件箱"
        assert data["watch_id"] == "inbox"
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers")
        assert status == 200
        by_id = {item["watch_id"]: item for item in payload["watchers"]}
        assert by_id["inbox"]["title"] == "收件箱"

        status, data = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/events?tail=1")
        assert status == 200
        assert [item["id"] for item in data["items"]] == ["evt_inbox"]
        status, data = _get(f"http://127.0.0.1:{port}/api/watchers/reports/events?tail=1")
        assert status == 200
        assert [item["id"] for item in data["items"]] == ["evt_reports"]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_web_events_page_and_time_range(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    store = _seed_watcher(
        "inbox",
        inbox,
        {"id": "e1", "type": "created", "path": "a.txt", "ts": "2026-09-17T10:00:00Z"},
    )
    store.append("events", {"id": "e2", "type": "modified", "path": "b.txt", "ts": "2026-09-17T11:00:00Z"})
    store.append("events", {"id": "e3", "type": "created", "path": "c.txt", "ts": "2026-09-17T12:00:00Z"})

    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, data = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/events?page=1&page_size=2")
        assert status == 200
        assert data["total"] == 3
        assert data["pages"] == 2
        assert data["page_size"] == 2
        assert [item["id"] for item in data["items"]] == ["e3", "e2"]
        status, data = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/events?page=2&page_size=2")
        assert status == 200
        assert [item["id"] for item in data["items"]] == ["e1"]
        status, data = _get(
            f"http://127.0.0.1:{port}/api/watchers/inbox/events?"
            + urllib.parse.urlencode(
                {
                    "page": 1,
                    "type": "created",
                    "ts_from": "2026-09-17T18:30:00+08:00",
                    "ts_to": "2026-09-17T20:00:59+08:00",
                }
            )
        )
        assert status == 200
        assert [item["id"] for item in data["items"]] == ["e3"]
        assert data["total"] == 1
        status, data = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/events?page=1&ts_from=not-a-date")
        assert status == 400
        assert data["error"] == "bad_request"
        status, data = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/events?page=1&q=B.TXT")
        assert status == 200
        assert [item["id"] for item in data["items"]] == ["e2"]
        assert data["total"] == 1
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
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules/from-text",
            {
                "text": "- name: skip-logs\n  exclude: true\n  when:\n    glob: ['**/*.log']\n",
                "apply": True,
            },
        )
        assert status == 200, payload
        assert payload["config"]["rules"][0]["name"] == "skip-logs"
        assert payload["config"]["rules"][0]["exclude"] is True
        assert payload["config"]["rules"][0]["then"] == []

        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules/0/from-text",
            {
                "text": "- name: skip-logs\n  exclude: true\n  when:\n    glob: ['**/*.tmp']\n",
                "apply": True,
            },
        )
        assert status == 200, payload
        assert payload["config"]["rules"][0]["when"]["glob"] == ["**/*.tmp"]
        assert len(payload["config"]["rules"]) == 1

        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules/9/from-text",
            {"text": "改一下", "apply": False},
        )
        assert status == 400
        assert payload["error"] == "bad_request"

        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules",
            {
                "rules": [
                    {
                        "name": "manual",
                        "when": {
                            "types": ["deleted"],
                            "glob": ["**/*.txt"],
                            "is_dir": False,
                            "active": {"start": "09:00", "end": "18:00", "days": ["mon", "tue", "wed", "thu", "fri"]},
                        },
                        "then": [{"notify": {"title": "删了", "message": "{{path}}"}}],
                    }
                ]
            },
        )
        assert status == 200, payload
        assert payload["rules"] == ["manual"]
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/config")
        assert payload["config"]["rules"][0]["name"] == "manual"
        assert payload["config"]["rules"][0]["when"]["active"] == {
            "start": "09:00",
            "end": "18:00",
            "days": ["mon", "tue", "wed", "thu", "fri"],
        }

        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules",
            {
                "rules": [
                    {
                        "name": "ding",
                        "when": {"types": ["created"], "glob": ["**/*"], "is_dir": False},
                        "then": [
                            {
                                "notify": {
                                    "title": "文件有变化",
                                    "message": "{{filename}}",
                                    "dingtalk": {
                                        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
                                        "secret": "SECxxx",
                                    },
                                }
                            }
                        ],
                    }
                ]
            },
        )
        assert status == 200, payload
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/config")
        ding = payload["config"]["rules"][0]["then"][0]["notify"]["dingtalk"]
        assert ding["webhook"].endswith("access_token=tok")
        assert ding["secret"] == "SECxxx"
        assert ding["interval_seconds"] == 60

        status, payload = _put(
            f"http://127.0.0.1:{port}/api/settings",
            {
                "dingtalk": {
                    "channels": [
                        {
                            "id": "work",
                            "name": "工作群",
                            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=from-settings",
                            "secret": "SECfromsettings",
                        }
                    ]
                }
            },
        )
        assert status == 200, payload
        assert payload["dingtalk"]["channels"][0]["id"] == "work"
        assert "SECfromsettings" not in json.dumps(payload)
        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules",
            {
                "rules": [
                    {
                        "name": "ding-channel",
                        "when": {"types": ["created"], "glob": ["**/*"], "is_dir": False},
                        "then": [{"notify": {"title": "文件有变化", "message": "{{filename}}", "dingtalk": {"channel": "work"}}}],
                    }
                ]
            },
        )
        assert status == 200, payload
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/config")
        ding = payload["config"]["rules"][0]["then"][0]["notify"]["dingtalk"]
        assert ding == {"channel": "work"}

        status, payload = _put(
            f"http://127.0.0.1:{port}/api/settings",
            {
                "dingtalk": {
                    "channels": [
                        {
                            "name": "备用群",
                            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=second",
                            "secret": "SECsecond",
                            "interval_seconds": 60,
                        }
                    ]
                }
            },
        )
        assert status == 200, payload
        assert len(payload["dingtalk"]["channels"]) == 1
        assert payload["dingtalk"]["channels"][0]["name"] == "备用群"
        status, payload = _get(f"http://127.0.0.1:{port}/api/settings")
        assert status == 200
        assert len(payload["dingtalk"]["channels"]) == 1
        assert payload["dingtalk"]["channels"][0]["webhook"].endswith("access_token=second")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_web_settings_and_llm_from_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _seed_watcher("inbox", inbox, {"id": "evt_inbox", "type": "created", "path": str(inbox / "a.txt")})

    def fake_complete(system: str, _user: str) -> str:
        if "规则编辑器" in system:
            return json.dumps(
                {
                    "notes": ["edited"],
                    "rule": {
                        "name": "created-md",
                        "when": {"types": ["created", "modified"], "glob": ["**/*.txt"], "is_dir": False},
                        "then": [{"notify": {"title": "t", "message": "{{filename}}"}}],
                    },
                }
            )
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
        assert payload["watch"]["debounce_ms"] == 400
        assert payload["watch"]["line_diff_quiet_ms"] == 30_000
        assert payload["watch"]["line_diff_max_bytes"] == 256 * 1024
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
        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules/0/from-text",
            {"text": "改成匹配 txt，并加上修改事件", "apply": True},
        )
        assert status == 200, payload
        rule = payload["config"]["rules"][0]
        assert rule["name"] == "created-md"
        assert rule["when"]["glob"] == ["**/*.txt"]
        assert rule["when"]["types"] == ["created", "modified"]
        assert len(payload["config"]["rules"]) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_web_health_and_invalid_requests(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _seed_watcher("inbox", inbox, {"id": "evt_inbox", "type": "created", "path": str(inbox / "a.txt")})
    monkeypatch.setattr(
        "filewatch.web.test_llm_connection",
        lambda: {"ok": False, "error": "llm_not_configured", "message": "请先填写 API Key"},
    )
    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, payload = _get(f"http://127.0.0.1:{port}/api/health")
        assert status == 200
        assert payload["ok"] is True
        status, payload = _post(f"http://127.0.0.1:{port}/api/settings/test", {})
        assert status == 400
        assert payload["error"] == "llm_not_configured"
        status, payload = _post(f"http://127.0.0.1:{port}/api/watchers/start", {})
        assert status == 400
        assert payload["error"] == "bad_request"
        status, payload = _post(f"http://127.0.0.1:{port}/api/watchers/start", {"path": str(tmp_path / "missing")})
        assert status == 404
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers/not.valid/events")
        assert status == 400
        assert payload["error"] == "bad_id"
        status, payload = _post(f"http://127.0.0.1:{port}/api/watchers/inbox/rules/from-text", {})
        assert status == 400
        assert payload["error"] == "bad_request"
        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules/from-text",
            {"text": "新建 markdown", "apply": False, "mode": "replace"},
        )
        assert status == 400
        assert payload["error"] == "bad_request"
        status, payload = _post(f"http://127.0.0.1:{port}/api/watchers/nope/rules", {"rules": []})
        assert status == 404
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/settings",
            data=b"[1]",
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request, timeout=5)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert body["error"] == "bad_json"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_web_save_rules_reloads_running(tmp_path: Path, monkeypatch) -> None:
    import os
    import threading

    from filewatch.runtime import WatchRuntime

    home = tmp_path / "home"
    monkeypatch.setenv("FILEWATCH_HOME", str(home))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    store = _seed_watcher("inbox", inbox, {"id": "evt_inbox", "type": "created", "path": str(inbox / "a.txt")})
    config = parse_config_dict(
        {
            "name": "inbox",
            "watch": {"path": str(inbox), "debounce_ms": 1},
            "rules": [],
        }
    )
    runtime = WatchRuntime(config, store)
    store.write_pid(os.getpid())
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            runtime._poll_control()
            time.sleep(0.05)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/inbox/rules",
            {
                "rules": [
                    {
                        "name": "hot",
                        "when": {"types": ["created"], "glob": ["**/*.md"], "is_dir": False},
                        "then": [{"notify": {"title": "t", "message": "{{filename}}"}}],
                    }
                ]
            },
        )
        assert status == 200, payload
        assert payload["reloaded"] is True
        assert any(rule.name == "hot" for rule in runtime.config.rules)
    finally:
        stop.set()
        thread.join(timeout=2)
        runtime.debouncer.close()
        runtime.actions.close(wait=False)
        httpd.shutdown()
        httpd.server_close()


def test_web_saves_watch_timing_to_existing_task(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FILEWATCH_LLM_API_KEY", raising=False)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _seed_watcher("inbox", inbox, {"id": "evt_inbox", "type": "created", "path": str(inbox / "a.txt")})
    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, payload = _put(
            f"http://127.0.0.1:{port}/api/settings",
            {"watch": {"debounce_ms": 180, "line_diff_quiet_ms": 45000, "line_diff_max_bytes": 512000}},
        )
        assert status == 200, payload
        assert payload["watch"]["debounce_ms"] == 180
        assert payload["watch"]["line_diff_quiet_ms"] == 45000
        assert payload["watch"]["line_diff_max_bytes"] == 512000
        assert payload["applied_watchers"][0]["watch_id"] == "inbox"
        status, config = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/config")
        assert status == 200
        assert config["config"]["watch"]["debounce_ms"] == 180
        assert config["config"]["watch"]["line_diff_quiet_ms"] == 45000
        assert config["config"]["watch"]["line_diff_max_bytes"] == 512000
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_web_save_watch_record_all(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    _seed_watcher("inbox", inbox, {"id": "evt_inbox", "type": "created", "path": str(inbox / "a.txt")})
    httpd = serve_http("127.0.0.1", 0)
    try:
        port = httpd.server_address[1]
        status, payload = _get(f"http://127.0.0.1:{port}/api/watchers")
        assert status == 200
        assert payload["watchers"][0]["record_all"] is True
        status, payload = _put(f"http://127.0.0.1:{port}/api/watchers/inbox/watch", {"record_all": False})
        assert status == 200, payload
        assert payload["ok"] is True
        assert payload["record_all"] is False
        status, config = _get(f"http://127.0.0.1:{port}/api/watchers/inbox/config")
        assert status == 200
        assert config["config"]["watch"]["record_all"] is False
        status, payload = _put(f"http://127.0.0.1:{port}/api/watchers/inbox/watch", {})
        assert status == 400
        assert payload["error"] == "bad_request"
        status, payload = _put(f"http://127.0.0.1:{port}/api/watchers/inbox/watch", {"record_all": "no"})
        assert status == 400
        status, payload = _post(
            f"http://127.0.0.1:{port}/api/watchers/start",
            {"path": str(inbox), "record_all": "yes"},
        )
        assert status == 400
        assert payload["error"] == "bad_request"
    finally:
        httpd.shutdown()
        httpd.server_close()

