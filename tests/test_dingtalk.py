from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request

import pytest

from filewatch.actions import ActionRunner
from filewatch.config import ConfigError, config_to_dict, parse_config_dict
from filewatch.dingtalk import (
    DingTalkBatcher,
    coalesce_items,
    format_agent_reply,
    format_markdown,
    send_dingtalk,
    signed_webhook,
    probe_dingtalk_channel,
)
from filewatch.models import DingTalkTarget, FileEvent
from filewatch.store import WatchStore


def test_signed_webhook_stable() -> None:
    url = "https://oapi.dingtalk.com/robot/send?access_token=tok"
    signed = signed_webhook(url, "SECdemo", timestamp_ms=1700000000000)
    assert "timestamp=1700000000000" in signed
    assert "sign=" in signed
    assert signed_webhook(url, "SECdemo", timestamp_ms=1700000000000) == signed
    assert signed_webhook(url, None) == url


def test_format_and_coalesce() -> None:
    items = [
        {
            "title": "文件有变化",
            "message": "created: a.md",
            "rule": "docs",
            "event": {"type": "created", "path": "a.md"},
        },
        {
            "title": "文件有变化",
            "message": "created: a.md (again)",
            "rule": "docs",
            "event": {"type": "created", "path": "a.md"},
        },
        {
            "title": "文件有变化",
            "message": "modified: b.txt",
            "rule": "docs",
            "event": {"type": "modified", "path": "b.txt"},
        },
    ]
    grouped = coalesce_items(items)
    assert len(grouped) == 2
    assert grouped[0]["message"] == "created: a.md (again)"
    title, text = format_markdown(items)
    assert title == "文件有变化"
    assert "共 **2** 条变化" in text
    assert "modified: b.txt" in text


def test_format_markdown_truncates_long_payload() -> None:
    items = [
        {
            "title": "文件有变化",
            "message": ("很长的路径/" * 80) + f"file-{index}.md",
            "rule": "docs",
            "event": {"type": "created", "path": f"file-{index}.md"},
        }
        for index in range(80)
    ]
    _, text = format_markdown(items)
    assert "其余条目已省略" in text
    assert len(text.encode("utf-8")) <= 18000


def test_format_agent_reply_uses_last_text() -> None:
    title, text = format_agent_reply("已重写 docs/a.md\n共 3 个文件")
    assert title == "已重写 docs/a.md"
    assert text == "已重写 docs/a.md\n共 3 个文件"


def test_format_agent_reply_truncates_long_payload() -> None:
    body = "总结\n" + ("很长的回复" * 4000)
    title, text = format_agent_reply(body)
    assert title == "总结"
    assert "其余内容已省略" in text
    assert len(text.encode("utf-8")) <= 18000


def test_parse_agent_dingtalk_roundtrip() -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": "."},
            "rules": [
                {
                    "name": "task",
                    "when": {"types": ["created"]},
                    "then": [
                        {
                            "agent": {
                                "runner": "builtin",
                                "prompt": "rewrite",
                                "dingtalk": True,
                            }
                        },
                        {
                            "agent": {
                                "runner": "builtin",
                                "prompt": "rewrite",
                                "dingtalk": {"channel": "work"},
                            }
                        },
                    ],
                }
            ],
        }
    )
    assert config.rules[0].then[0].dingtalk.channel == "*"  # type: ignore[union-attr]
    dumped = config_to_dict(config)
    assert dumped["rules"][0]["then"][0]["agent"]["dingtalk"] is True
    assert dumped["rules"][0]["then"][1]["agent"]["dingtalk"] == {"channel": "work"}


def test_parse_dingtalk_and_roundtrip() -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": "."},
            "rules": [
                {
                    "name": "docs",
                    "when": {"types": ["created"], "glob": "**/*.md"},
                    "then": [
                        {
                            "notify": {
                                "title": "t",
                                "message": "{{filename}}",
                                "dingtalk": {
                                    "webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
                                    "sec": "SECxxx",
                                },
                            }
                        }
                    ],
                }
            ],
        }
    )
    action = config.rules[0].then[0]
    assert action.dingtalk is not None
    assert action.dingtalk.secret == "SECxxx"
    assert action.dingtalk.interval_seconds == 60
    dumped = config_to_dict(config)
    assert dumped["rules"][0]["then"][0]["notify"]["dingtalk"]["secret"] == "SECxxx"


def test_parse_dingtalk_channel_and_true() -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": "."},
            "rules": [
                {
                    "name": "docs",
                    "when": {"types": ["created"]},
                    "then": [{"notify": {"dingtalk": True}}],
                },
                {
                    "name": "named",
                    "when": {"types": ["created"]},
                    "then": [{"notify": {"dingtalk": {"channel": "work"}}}],
                },
            ],
        }
    )
    assert config.rules[0].then[0].dingtalk.channel == "*"
    assert config_to_dict(config)["rules"][0]["then"][0]["notify"]["dingtalk"] is True
    assert config.rules[1].then[0].dingtalk.channel == "work"
    assert config_to_dict(config)["rules"][1]["then"][0]["notify"]["dingtalk"] == {"channel": "work"}


def test_parse_dingtalk_rejects_bad_url() -> None:
    with pytest.raises(ConfigError, match="http"):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [
                    {
                        "name": "docs",
                        "when": {"types": ["created"]},
                        "then": [{"notify": {"dingtalk": {"webhook": "not-a-url"}}}],
                    }
                ],
            }
        )


def test_empty_dingtalk_is_none() -> None:
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": "."},
            "rules": [
                {
                    "name": "docs",
                    "when": {"types": ["created"]},
                    "then": [{"notify": {"dingtalk": {"webhook": "", "secret": ""}}}],
                }
            ],
        }
    )
    assert config.rules[0].then[0].dingtalk is None


def test_secret_without_webhook_is_invalid() -> None:
    with pytest.raises(ConfigError, match="webhook"):
        parse_config_dict(
            {
                "name": "demo",
                "watch": {"path": "."},
                "rules": [
                    {
                        "name": "docs",
                        "when": {"types": ["created"]},
                        "then": [{"notify": {"dingtalk": {"secret": "SECxxx"}}}],
                    }
                ],
            }
        )


def test_batcher_polls_once_per_interval() -> None:
    posted: list[tuple[str, str | None, dict]] = []
    clock = {"now": 0.0}
    batcher = DingTalkBatcher(
        sender=lambda webhook, secret, payload: posted.append((webhook, secret, payload)),
        time_fn=lambda: clock["now"],
        origin=0.0,
    )
    target = DingTalkTarget(
        webhook="https://oapi.dingtalk.com/robot/send?access_token=tok",
        secret="SECxxx",
        interval_seconds=60,
    )
    item_a = {
        "title": "文件有变化",
        "message": "created: a.md",
        "rule": "docs",
        "watch_id": "demo",
        "event": {"type": "created", "path": "a.md"},
    }
    item_b = {
        "title": "文件有变化",
        "message": "modified: b.md",
        "rule": "docs",
        "watch_id": "demo",
        "event": {"type": "modified", "path": "b.md"},
    }
    batcher.enqueue(target, item_a)
    clock["now"] = 10
    batcher.enqueue(target, item_b)
    clock["now"] = 59
    assert batcher.flush_due() == 0
    assert posted == []
    clock["now"] = 60
    assert batcher.flush_due() == 1
    assert len(posted) == 1
    text = posted[0][2]["markdown"]["text"]
    assert "created: a.md" in text
    assert "modified: b.md" in text
    clock["now"] = 90
    batcher.enqueue(target, item_a)
    assert batcher.flush_due() == 0
    clock["now"] = 120
    assert batcher.flush_due() == 1
    assert len(posted) == 2


def test_send_dingtalk_checks_errcode(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeResp:
        def read(self) -> bytes:
            return b'{"errcode":310000,"errmsg":"sign error"}'

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    def fake_urlopen(request: Request, timeout: float = 15):
        captured["url"] = request.full_url
        return FakeResp()

    monkeypatch.setattr("filewatch.dingtalk.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="310000"):
        send_dingtalk(
            "https://oapi.dingtalk.com/robot/send?access_token=tok",
            "SECdemo",
            {"msgtype": "text", "text": {"content": "hi"}},
        )
    assert "timestamp=" in captured["url"]
    assert "sign=" in captured["url"]


def test_probe_dingtalk_channel_sends_markdown(monkeypatch) -> None:
    posted: list[tuple[str, str | None, dict]] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append((webhook, secret, payload)),
    )
    result = probe_dingtalk_channel(
        webhook="https://oapi.dingtalk.com/robot/send?access_token=tok",
        secret="SECdemo",
        name="工作群",
    )
    assert result["ok"] is True
    assert "工作群" in result["message"]
    assert posted[0][0].startswith("https://oapi.dingtalk.com/")
    assert posted[0][1] == "SECdemo"
    assert posted[0][2]["msgtype"] == "markdown"
    assert "测试" in posted[0][2]["markdown"]["text"]


def test_probe_dingtalk_channel_rejects_empty_webhook() -> None:
    result = probe_dingtalk_channel(webhook="  ", secret=None, name="x")
    assert result["ok"] is False
    assert result["error"] == "bad_request"


def test_notify_queues_dingtalk_until_flush(tmp_path: Path, monkeypatch) -> None:
    posted: list[dict] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append(payload),
    )
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(inbox)},
            "rules": [
                {
                    "name": "docs",
                    "when": {"types": ["created"], "glob": "**/*"},
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
            ],
        }
    )
    store = WatchStore("demo", root=tmp_path / "state")
    store.ensure()
    runner = ActionRunner(store)
    event = FileEvent(
        id="evt_1",
        ts="2026-01-01T00:00:00Z",
        watch_id="demo",
        type="created",
        path=str(inbox / "note.md"),
        is_dir=False,
    )
    try:
        runner.submit(event, config.rules[0])
        items: list[dict] = []
        cursor = 0
        for _ in range(20):
            chunk, cursor, _ = store.wait("jobs", cursor, timeout=0.2, limit=10)
            items.extend(chunk)
            if any(job.get("dingtalk") == "queued" for job in items):
                break
        assert any(job.get("dingtalk") == "queued" for job in items)
        assert posted == []
        assert runner._dingtalk is not None
        runner._dingtalk.flush_all()
        assert len(posted) == 1
        assert "note.md" in posted[0]["markdown"]["text"]
        batched, _, _ = store.wait("jobs", cursor, timeout=1, limit=10)
        assert any(job.get("batched") and job.get("dingtalk") == "ok" for job in batched)
    finally:
        runner.close(wait=True)


def test_notify_resolves_dingtalk_channel_from_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FILEWATCH_HOME", str(tmp_path / "home"))
    posted: list[dict] = []
    monkeypatch.setattr(
        "filewatch.dingtalk.send_dingtalk",
        lambda webhook, secret, payload: posted.append({"webhook": webhook, "secret": secret, "payload": payload}),
    )
    from filewatch.settings import save_settings

    save_settings(
        {
            "dingtalk": {
                "channels": [
                    {
                        "id": "work",
                        "name": "工作群",
                        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=tok",
                        "secret": "SECxxx",
                    }
                ]
            }
        }
    )
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    config = parse_config_dict(
        {
            "name": "demo",
            "watch": {"path": str(inbox)},
            "rules": [
                {
                    "name": "docs",
                    "when": {"types": ["created"], "glob": ["**/*"]},
                    "then": [{"notify": {"title": "文件有变化", "message": "{{filename}}", "dingtalk": {"channel": "work"}}}],
                }
            ],
        }
    )
    store = WatchStore("demo", root=tmp_path / "state")
    store.ensure()
    runner = ActionRunner(store)
    event = FileEvent(
        id="evt_1",
        ts="2026-01-01T00:00:00Z",
        watch_id="demo",
        type="created",
        path=str(inbox / "note.md"),
        is_dir=False,
    )
    try:
        runner.submit(event, config.rules[0])
        items: list[dict] = []
        cursor = 0
        for _ in range(20):
            chunk, cursor, _ = store.wait("jobs", cursor, timeout=0.2, limit=10)
            items.extend(chunk)
            if any(job.get("dingtalk") == "queued" for job in items):
                break
        assert any(job.get("dingtalk") == "queued" for job in items)
        assert runner._dingtalk is not None
        runner._dingtalk.flush_all()
        assert len(posted) == 1
        assert posted[0]["webhook"].endswith("access_token=tok")
        assert posted[0]["secret"] == "SECxxx"
        assert "note.md" in posted[0]["payload"]["markdown"]["text"]
    finally:
        runner.close(wait=True)
