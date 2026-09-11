from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from filewatch.dingtalk import DingTalkBatcher
from filewatch.models import AgentAction, FileEvent, NotifyAction, Rule
from filewatch.store import WatchStore
from filewatch.templates import render, render_argv


class ActionRunner:
    def __init__(
        self,
        store: WatchStore,
        max_workers: int = 1,
        *,
        workspace: Path | None = None,
        suppress: Callable[[str, float], None] | None = None,
    ) -> None:
        self.store = store
        self.workspace = workspace
        self.suppress = suppress
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="filewatch-job")
        self._dingtalk: DingTalkBatcher | None = None
        self._dingtalk_lock = threading.Lock()

    def submit(self, event: FileEvent, rule: Rule) -> None:
        for index, action in enumerate(rule.then):
            self._pool.submit(self._run_one, event, rule, action, index)

    def _run_one(self, event: FileEvent, rule: Rule, action: NotifyAction | AgentAction, index: int) -> None:
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "id": job_id,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "watch_id": event.watch_id,
            "rule": rule.name,
            "action_index": index,
            "event": event.to_dict(),
            "status": "running",
        }
        if isinstance(action, NotifyAction):
            record["kind"] = "notify"
            record.update(self._notify(action, event, rule))
        else:
            record["kind"] = "agent"
            record.update(self._agent(action, event, rule, job_id))
        self.store.append("jobs", record)

    def _notify(self, action: NotifyAction, event: FileEvent, rule: Rule) -> dict[str, Any]:
        extra = {"rule": rule.name, "title": action.title}
        title = render(action.title, event, extra)
        message = render(action.message, event, extra)
        result: dict[str, Any] = {
            "title": title,
            "message": message,
            "status": "ok",
        }
        errors: list[str] = []
        if action.webhook:
            payload = {
                "title": title,
                "message": message,
                "rule": rule.name,
                "event": event.to_dict(),
            }
            try:
                self._post_webhook(action.webhook, payload)
                result["webhook"] = "ok"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"webhook: {exc}")
                result["webhook"] = "error"
        if action.dingtalk:
            try:
                self._batcher().enqueue(
                    action.dingtalk,
                    {
                        "title": title,
                        "message": message,
                        "rule": rule.name,
                        "watch_id": event.watch_id,
                        "event": event.to_dict(),
                    },
                )
                result["dingtalk"] = "queued"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"dingtalk: {exc}")
                result["dingtalk"] = "error"
        if errors:
            result["status"] = "error"
            result["error"] = "; ".join(errors)
        return result

    def _post_webhook(self, url: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            response.read()

    def _agent(
        self,
        action: AgentAction,
        event: FileEvent,
        rule: Rule,
        job_id: str,
    ) -> dict[str, Any]:
        extra = {"rule": rule.name}
        prompt = render(action.prompt, event, extra)
        cwd = render(action.cwd, event, extra) if action.cwd else None
        try:
            if action.runner == "cursor_sdk":
                output = self._run_cursor_sdk(prompt, cwd, action)
                return {"status": "ok", "runner": action.runner, "prompt": prompt, "output": output[-4000:]}
            if action.runner == "builtin":
                return self._run_builtin(action, event, prompt, cwd, job_id)
            output = self._run_command(action, event, extra, prompt, cwd)
            return {"status": "ok", "runner": action.runner, "prompt": prompt, "output": output[-4000:]}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "runner": action.runner, "prompt": prompt, "error": str(exc)}

    def _resolve_workspace(self, cwd: str | None) -> Path:
        root = self.workspace or Path.cwd()
        root = root.resolve()
        if not cwd:
            return root
        candidate = Path(cwd)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            return root
        if resolved == root or root in resolved.parents:
            return resolved
        return root

    def _run_builtin(
        self,
        action: AgentAction,
        event: FileEvent,
        prompt: str,
        cwd: str | None,
        job_id: str,
    ) -> dict[str, Any]:
        from filewatch.agent.loop import run_builtin_agent

        workspace = self._resolve_workspace(cwd)
        log_dir = self.store.dir / "agent-logs"
        result = run_builtin_agent(
            prompt=prompt,
            event=event,
            workspace=workspace,
            job_id=job_id,
            log_dir=log_dir,
            timeout_seconds=action.timeout_seconds,
            max_steps=action.max_steps,
            model=action.model,
            suppress=self.suppress,
        )
        record: dict[str, Any] = {
            "status": result.status,
            "runner": "builtin",
            "prompt": prompt,
            "output": result.output,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "log": result.log_path,
        }
        if result.error:
            record["error"] = result.error
        if result.message:
            record["message"] = result.message
        return record

    def _run_command(
        self,
        action: AgentAction,
        event: FileEvent,
        extra: dict[str, Any],
        prompt: str,
        cwd: str | None,
    ) -> str:
        if not action.command:
            raise RuntimeError("agent.command is required")
        argv = render_argv(action.command, event, extra)
        env = os.environ.copy()
        env["FILEWATCH_PROMPT"] = prompt
        env["FILEWATCH_EVENT_JSON"] = json.dumps(event.to_dict(), ensure_ascii=False)
        env["FILEWATCH_RULE"] = str(extra.get("rule", ""))
        completed = subprocess.run(
            argv,
            input=prompt,
            cwd=cwd or None,
            env=env,
            capture_output=True,
            text=True,
            timeout=action.timeout_seconds,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            raise RuntimeError(f"agent command exited {completed.returncode}: {output[-2000:]}")
        return output

    def _run_cursor_sdk(self, prompt: str, cwd: str | None, action: AgentAction) -> str:
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
        except ImportError as exc:
            raise RuntimeError("cursor-sdk is not installed; pip install cursor-sdk") from exc
        options = AgentOptions(
            api_key=os.environ.get("CURSOR_API_KEY"),
            model=action.model or "composer-2.5",
            local=LocalAgentOptions(cwd=cwd or os.getcwd()),
        )
        result = Agent.prompt(prompt, options)
        status = getattr(result, "status", None)
        text = getattr(result, "result", None) or getattr(result, "text", None) or str(result)
        if status and str(status) not in {"finished", "ok", "success"}:
            raise RuntimeError(f"cursor agent status={status}: {text}")
        return str(text)

    def _batcher(self) -> DingTalkBatcher:
        with self._dingtalk_lock:
            if self._dingtalk is None:
                self._dingtalk = DingTalkBatcher(
                    sender=self._send_dingtalk,
                    on_flushed=self._on_dingtalk_flushed,
                )
                self._dingtalk.start()
            return self._dingtalk

    def _send_dingtalk(self, webhook: str, secret: str | None, payload: dict[str, Any]) -> None:
        from filewatch import dingtalk as ding

        ding.send_dingtalk(webhook, secret, payload)

    def _on_dingtalk_flushed(self, record: dict[str, Any]) -> None:
        job = {
            "id": f"job_{uuid.uuid4().hex[:12]}",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": "notify",
            "batched": True,
            **record,
        }
        self.store.append("jobs", job)

    def close(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)
        with self._dingtalk_lock:
            batcher = self._dingtalk
            self._dingtalk = None
        if batcher is not None:
            batcher.close()
