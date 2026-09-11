from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from filewatch.config import (
    ConfigError,
    config_from_path,
    config_to_dict,
    load_config,
    parse_config_dict,
    summarize_config,
)
from filewatch.models import EVENT_TYPES, STREAMS, FileEvent
from filewatch.paths import sanitize_id
from filewatch.process import pid_alive
from filewatch.rules import RuleEngine
from filewatch.runtime import WatchRuntime, new_id, utc_now
from filewatch.service import (
    describe_watcher,
    list_watcher_payloads,
    start_watch,
    stop_watch,
)
from filewatch.store import WatchStore, list_stores

SAMPLE_CONFIG = """name: inbox
max_parallel_jobs: 1
watch:
  path: ./inbox
  recursive: true
  debounce_ms: 400
  ignore:
    - "**/.git/**"
    - "**/__pycache__/**"
    - "**/.venv/**"
    - "**/*.tmp"
rules:
  - name: any-file-change
    when:
      types: [created, modified]
      glob: "**/*"
      is_dir: false
    then:
      - notify:
          title: "文件有变化"
          message: "{{type}}: {{path}}"
          mailbox: true
          # dingtalk:
          #   webhook: "https://oapi.dingtalk.com/robot/send?access_token=TOKEN"
          #   secret: "SECxxx"
          #   interval_seconds: 60
  # 取消注释后，新建 markdown 时会启动智能体。
  # - name: summarize-markdown
  #   when:
  #     types: [created]
  #     glob: "**/*.md"
  #     cooldown_seconds: 30
  #   then:
  #     - notify:
  #         title: "新建 markdown"
  #         message: "{{filename}} 已创建"
  #     - agent:
  #         runner: command
  #         command: ["python", "scripts/echo_agent.py"]
  #         prompt: |
  #           新建文件：{{path}}
  #           事件：{{type}}
  #           请处理该文件。
  #         timeout_seconds: 600
  #     # 若已安装 cursor-sdk 并配置 CURSOR_API_KEY：
  #     # - agent:
  #     #     runner: cursor_sdk
  #     #     model: composer-2.5
  #     #     prompt: "处理新文件 {{path}}"
"""


def emit(payload: dict[str, Any], code: int = 0, pretty: bool = False) -> int:
    indent = 2 if pretty else None
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=indent)
    sys.stdout.write("\n")
    return code


def fail(error: str, message: str, pretty: bool = False, **extra: Any) -> int:
    payload = {"ok": False, "error": error, "message": message, **extra}
    return emit(payload, 1, pretty=pretty)


def _pretty(ns: argparse.Namespace) -> bool:
    return bool(getattr(ns, "pretty", False))


def _store(watch_id: str) -> WatchStore:
    return WatchStore(sanitize_id(watch_id))


def _resolve_id(explicit: str | None, pretty: bool) -> tuple[str | None, int | None]:
    if explicit:
        return sanitize_id(explicit), None
    stores = list_stores()
    if len(stores) == 1:
        return stores[0].watch_id, None
    if not stores:
        return None, fail("no_watchers", "没有找到监听实例；请传入 --id 或先 start", pretty=pretty)
    ids = [item.watch_id for item in stores]
    return None, fail("ambiguous_watch", "存在多个监听实例；请传入 --id", pretty=pretty, watch_ids=ids)


def _running(store: WatchStore) -> tuple[bool, int | None]:
    pid = store.read_pid()
    if pid and pid_alive(pid):
        return True, pid
    return False, pid


def cmd_init(ns: argparse.Namespace) -> int:
    target = Path(ns.output).expanduser().resolve()
    if target.exists() and not ns.force:
        return fail("exists", f"配置已存在：{target}", pretty=_pretty(ns), path=str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(SAMPLE_CONFIG, encoding="utf-8")
    inbox = target.parent / "inbox"
    inbox.mkdir(exist_ok=True)
    return emit({"ok": True, "path": str(target), "inbox": str(inbox)}, pretty=_pretty(ns))


def _load_from_args(ns: argparse.Namespace) -> Config:
    if ns.config:
        return load_config(ns.config)
    if ns.path:
        return config_from_path(ns.path, name=ns.id, recursive=not ns.no_recursive)
    raise ConfigError("必须提供 --config 或 --path")


def cmd_start(ns: argparse.Namespace) -> int:
    pretty = _pretty(ns)
    try:
        config = _load_from_args(ns)
    except ConfigError as exc:
        return fail("bad_config", str(exc), pretty=pretty)
    payload = start_watch(config, ns.id)
    return emit(payload, 0 if payload.get("ok") else 1, pretty=pretty)


def cmd_run(ns: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    store = _store(ns.id)
    if ns.config:
        config = load_config(ns.config)
    else:
        if not store.config_path.exists():
            return fail("not_found", f"没有找到监听 {ns.id} 的已保存配置")
        raw = json.loads(store.config_path.read_text(encoding="utf-8"))
        config = parse_config_dict(raw, source=str(store.config_path))
    runtime = WatchRuntime(config, store)
    runtime.run_forever()
    return 0


def cmd_stop(ns: argparse.Namespace) -> int:
    pretty = _pretty(ns)
    watch_id, err = _resolve_id(ns.id, pretty)
    if err is not None:
        return err
    assert watch_id is not None
    return emit(stop_watch(watch_id), pretty=pretty)


def cmd_status(ns: argparse.Namespace) -> int:
    pretty = _pretty(ns)
    watch_id, err = _resolve_id(ns.id, pretty)
    if err is not None:
        return err
    assert watch_id is not None
    return emit({"ok": True, **describe_watcher(_store(watch_id))}, pretty=pretty)


def cmd_list(ns: argparse.Namespace) -> int:
    return emit({"ok": True, "watchers": list_watcher_payloads()}, pretty=_pretty(ns))


def _read_stream(ns: argparse.Namespace, timeout: float) -> int:
    pretty = _pretty(ns)
    watch_id, err = _resolve_id(ns.id, pretty)
    if err is not None:
        return err
    assert watch_id is not None
    stream = ns.stream
    if stream not in STREAMS:
        return fail("bad_stream", f"stream 必须是 {STREAMS} 之一", pretty=pretty)
    store = _store(watch_id)
    store.ensure()
    since = ns.since if ns.since is not None else store.read_cursors().get(stream, 0)
    items, cursor, timed_out = store.wait(stream, since, timeout=timeout, limit=ns.max)
    return emit(
        {
            "ok": True,
            "watch_id": watch_id,
            "stream": stream,
            "timed_out": timed_out,
            "since": since,
            "cursor": cursor,
            "count": len(items),
            "items": items,
        },
        pretty=pretty,
    )


def cmd_wait(ns: argparse.Namespace) -> int:
    return _read_stream(ns, timeout=ns.timeout)


def cmd_drain(ns: argparse.Namespace) -> int:
    return _read_stream(ns, timeout=0)


def cmd_ack(ns: argparse.Namespace) -> int:
    pretty = _pretty(ns)
    watch_id, err = _resolve_id(ns.id, pretty)
    if err is not None:
        return err
    assert watch_id is not None
    store = _store(watch_id)
    try:
        cursors = store.ack(ns.stream, ns.cursor)
    except ValueError as exc:
        return fail("bad_cursor", str(exc), pretty=pretty)
    return emit({"ok": True, "watch_id": watch_id, "cursors": cursors}, pretty=pretty)


def cmd_test_rule(ns: argparse.Namespace) -> int:
    pretty = _pretty(ns)
    try:
        config = load_config(ns.config)
    except ConfigError as exc:
        return fail("bad_config", str(exc), pretty=pretty)
    path = str(Path(ns.path).expanduser().resolve())
    event = FileEvent(
        id=new_id("evt"),
        ts=utc_now(),
        watch_id=config.name,
        type=ns.type,
        path=path,
        is_dir=bool(ns.is_dir),
    )
    engine = RuleEngine(Path(config.watch.path), config.rules)
    hits = engine.matches(event)
    return emit(
        {
            "ok": True,
            "event": event.to_dict(),
            "matched": [rule.name for rule in hits],
            "count": len(hits),
        },
        pretty=pretty,
    )


def cmd_validate(ns: argparse.Namespace) -> int:
    pretty = _pretty(ns)
    try:
        config = load_config(ns.config)
    except ConfigError as exc:
        return fail("bad_config", str(exc), pretty=pretty)
    summary = summarize_config(config)
    watch_path = Path(config.watch.path)
    warnings: list[str] = []
    if not watch_path.is_dir():
        warnings.append(f"监听路径不是目录：{watch_path}")
    return emit(
        {
            "ok": True,
            "config": str(Path(ns.config).expanduser().resolve()),
            "watch_id": config.name,
            "warnings": warnings,
            **summary,
        },
        pretty=pretty,
    )


def cmd_reload(ns: argparse.Namespace) -> int:
    pretty = _pretty(ns)
    try:
        config = load_config(ns.config)
    except ConfigError as exc:
        return fail("bad_config", str(exc), pretty=pretty)
    watch_id, err = _resolve_id(ns.id or config.name, pretty)
    if err is not None:
        return err
    assert watch_id is not None
    store = _store(watch_id)
    running, pid = _running(store)
    if not running:
        return fail(
            "not_running",
            "监听未在运行，请先 start",
            pretty=pretty,
            watch_id=watch_id,
        )
    generation = uuid.uuid4().hex
    store.request_reload(config_to_dict(config), generation)
    timeout = max(float(ns.timeout), 0.5)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = store.read_reload_status()
        if status and status.get("generation") == generation:
            if status.get("ok"):
                return emit(
                    {
                        "ok": True,
                        "watch_id": watch_id,
                        "pid": pid,
                        "generation": generation,
                        "rules": status.get("rules") or [],
                        "warnings": status.get("warnings") or [],
                        "applied": status.get("applied") or summarize_config(config),
                    },
                    pretty=pretty,
                )
            return fail(
                str(status.get("error") or "reload_failed"),
                str(status.get("message") or "热更新失败"),
                pretty=pretty,
                watch_id=watch_id,
                generation=generation,
            )
        still_running, _ = _running(store)
        if not still_running:
            return fail("daemon_exited", "热更新期间守护进程已退出", pretty=pretty, watch_id=watch_id)
        time.sleep(0.1)
    return fail(
        "reload_timeout",
        "守护进程未在超时内应用配置",
        pretty=pretty,
        watch_id=watch_id,
        generation=generation,
    )


def cmd_serve(ns: argparse.Namespace) -> int:
    pretty = _pretty(ns)
    from filewatch.web import create_server

    httpd = create_server(ns.host, int(ns.port))
    host, port = httpd.server_address[:2]
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{display_host}:{port}/"
    emit({"ok": True, "url": url, "host": host, "port": port}, pretty=pretty)
    sys.stdout.flush()
    if ns.open:
        import webbrowser

        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("已停止 Web 服务", file=sys.stderr)
    finally:
        httpd.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filewatch",
        description="监听文件夹，并按规则发送通知或启动智能体任务。",
    )
    parser.add_argument("--home", help="覆盖 FILEWATCH_HOME 状态目录")
    parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="写入一份示例 watch.yaml")
    init.add_argument("--output", default="watch.yaml")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    start = sub.add_parser("start", help="以后台守护进程方式启动监听")
    start.add_argument("--config")
    start.add_argument("--path")
    start.add_argument("--id")
    start.add_argument("--no-recursive", action="store_true")
    start.set_defaults(func=cmd_start)

    run = sub.add_parser("run", help="在前台运行监听（供守护进程调用）")
    run.add_argument("--id", required=True)
    run.add_argument("--config")
    run.set_defaults(func=cmd_run)

    stop = sub.add_parser("stop", help="停止监听守护进程")
    stop.add_argument("--id")
    stop.set_defaults(func=cmd_stop)

    status = sub.add_parser("status", help="查看监听状态")
    status.add_argument("--id")
    status.set_defaults(func=cmd_status)

    listed = sub.add_parser("list", help="列出已知的监听实例")
    listed.set_defaults(func=cmd_list)

    def add_stream_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--id")
        p.add_argument("--stream", choices=STREAMS, default="events")
        p.add_argument("--since", type=int)
        p.add_argument("--max", type=int, default=50)

    wait = sub.add_parser("wait", help="阻塞等待邮箱中出现新记录")
    add_stream_args(wait)
    wait.add_argument("--timeout", type=float, default=30)
    wait.set_defaults(func=cmd_wait)

    drain = sub.add_parser("drain", help="非阻塞读取邮箱中的现有记录")
    add_stream_args(drain)
    drain.set_defaults(func=cmd_drain)

    ack = sub.add_parser("ack", help="推进消费游标")
    ack.add_argument("--id")
    ack.add_argument("--stream", choices=STREAMS, default="events")
    ack.add_argument("--cursor", type=int, required=True)
    ack.set_defaults(func=cmd_ack)

    test_rule = sub.add_parser("test-rule", help="干跑：查看哪些规则会命中该事件")
    test_rule.add_argument("--config", required=True)
    test_rule.add_argument("--path", required=True)
    test_rule.add_argument("--type", choices=EVENT_TYPES, default="created")
    test_rule.add_argument("--is-dir", action="store_true")
    test_rule.set_defaults(func=cmd_test_rule)

    validate = sub.add_parser("validate", help="检查配置和规则语法")
    validate.add_argument("--config", required=True)
    validate.set_defaults(func=cmd_validate)

    reload_cmd = sub.add_parser("reload", help="热更新运行中实例的规则，无需重启")
    reload_cmd.add_argument("--config", required=True)
    reload_cmd.add_argument("--id")
    reload_cmd.add_argument("--timeout", type=float, default=8)
    reload_cmd.set_defaults(func=cmd_reload)

    serve = sub.add_parser("serve", help="打开本地网页，展示指定文件夹的文件变化事件")
    serve.add_argument("--host", default="127.0.0.1", help="绑定地址，默认 127.0.0.1")
    serve.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    serve.add_argument("--open", action="store_true", help="启动后打开浏览器")
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    if ns.home:
        os.environ["FILEWATCH_HOME"] = str(Path(ns.home).expanduser().resolve())
    try:
        return int(ns.func(ns))
    except ConfigError as exc:
        return fail("bad_config", str(exc), pretty=_pretty(ns))
    except FileNotFoundError as exc:
        return fail("not_found", str(exc), pretty=_pretty(ns))
    except KeyboardInterrupt:
        return fail("interrupted", "已中断", pretty=_pretty(ns))


if __name__ == "__main__":
    raise SystemExit(main())
