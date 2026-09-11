from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from filewatch.agent.logging import ToolCallLogger
from filewatch.agent.types import ToolCall, ToolCallRecord, ToolContext, ToolResult, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in self._tools.values()
        ]

    def dispatch(
        self,
        calls: list[ToolCall],
        ctx: ToolContext,
        logger: ToolCallLogger | None = None,
    ) -> list[ToolCallRecord]:
        """按 LLM 给出的顺序调度：连续 parallel=true 并行，parallel=false 独占。"""
        records: list[ToolCallRecord] = []
        i = 0
        while i < len(calls):
            call = calls[i]
            spec = self._tools.get(call.name)
            if spec is None:
                record = self._unknown(call)
                records.append(record)
                if logger:
                    logger.log(record)
                i += 1
                continue
            if not spec.parallel:
                record = self._run_one(spec, call, ctx)
                records.append(record)
                if logger:
                    logger.log(record)
                i += 1
                continue
            batch: list[tuple[ToolSpec, ToolCall]] = []
            while i < len(calls):
                next_call = calls[i]
                next_spec = self._tools.get(next_call.name)
                if next_spec is None or not next_spec.parallel:
                    break
                batch.append((next_spec, next_call))
                i += 1
            if len(batch) == 1:
                record = self._run_one(batch[0][0], batch[0][1], ctx)
                records.append(record)
                if logger:
                    logger.log(record)
            else:
                batch_records = self._run_parallel(batch, ctx)
                records.extend(batch_records)
                if logger:
                    for record in batch_records:
                        logger.log(record)
        return records

    def _unknown(self, call: ToolCall) -> ToolCallRecord:
        result = ToolResult(
            ok=False,
            error="unknown_tool",
            message=f"未知工具：{call.name}",
        )
        return ToolCallRecord(
            id=call.id,
            name=call.name,
            arguments=call.arguments,
            result=result,
            duration_ms=0.0,
        )

    def _run_one(self, spec: ToolSpec, call: ToolCall, ctx: ToolContext) -> ToolCallRecord:
        started = time.perf_counter()
        try:
            result = spec.execute(call.arguments, ctx)
        except Exception as exc:  # noqa: BLE001
            result = ToolResult(ok=False, error="tool_exception", message=str(exc))
        duration_ms = (time.perf_counter() - started) * 1000
        return ToolCallRecord(
            id=call.id,
            name=call.name,
            arguments=call.arguments,
            result=result,
            duration_ms=duration_ms,
        )

    def _run_parallel(
        self,
        batch: list[tuple[ToolSpec, ToolCall]],
        ctx: ToolContext,
    ) -> list[ToolCallRecord]:
        results: dict[str, ToolCallRecord] = {}
        with ThreadPoolExecutor(max_workers=min(8, len(batch)), thread_name_prefix="fw-tool") as pool:
            futures = {
                pool.submit(self._run_one, spec, call, ctx): call.id for spec, call in batch
            }
            for future in as_completed(futures):
                call_id = futures[future]
                try:
                    results[call_id] = future.result()
                except Exception as exc:  # noqa: BLE001
                    results[call_id] = ToolCallRecord(
                        id=call_id,
                        name="?",
                        arguments={},
                        result=ToolResult(ok=False, error="tool_exception", message=str(exc)),
                        duration_ms=0.0,
                    )
        ordered: list[ToolCallRecord] = []
        for _, call in batch:
            record = results.get(call.id)
            if record is not None:
                ordered.append(record)
        return ordered
