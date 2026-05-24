"""Build and persist turn traces from agent run output."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from loguru import logger

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace, TurnTraceOutcome
from nanobot.agent.evolution.trace_store import TraceStore
from nanobot.config.schema import EvolutionConfig

_ARGS_SUMMARY_MAX = 200
_FAIL_STOP_REASONS = frozenset({"error", "tool_error", "max_iterations"})


def slice_turn_messages(
    messages: Sequence[dict[str, Any]],
    baseline_len: int,
) -> list[dict[str, Any]]:
    """Return messages appended during the current agent run."""
    if baseline_len < 0:
        baseline_len = 0
    return list(messages[baseline_len:])


def infer_outcome(stop_reason: str) -> TurnTraceOutcome:
    """Map runner stop_reason to a coarse trace outcome."""
    normalized = (stop_reason or "").strip()
    if normalized == "completed":
        return "success"
    if normalized in _FAIL_STOP_REASONS:
        return "fail"
    return "partial"


def _is_tool_error(content: object) -> bool:
    if content is None:
        return False
    text = str(content).strip()
    if not text:
        return False
    if text.startswith("Error:") or text.startswith("error:"):
        return True
    lowered = text.lower()
    return lowered.startswith("tool error") or lowered.startswith("execution failed")


def _summarize_tool_arguments(arguments: object) -> str:
    if arguments is None:
        return ""
    if isinstance(arguments, str):
        text = arguments.strip()
    else:
        try:
            text = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(arguments)
    if len(text) <= _ARGS_SUMMARY_MAX:
        return text
    return text[: _ARGS_SUMMARY_MAX - 3] + "..."


def _tool_call_id(message: dict[str, Any]) -> str | None:
    tool_call_id = message.get("tool_call_id")
    return str(tool_call_id) if tool_call_id else None


def _tool_result_lookup(messages: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for message in messages:
        if message.get("role") != "tool":
            continue
        tool_call_id = _tool_call_id(message)
        if tool_call_id:
            results[tool_call_id] = message
    return results


def parse_tool_calls_from_messages(
    messages: Sequence[dict[str, Any]],
) -> tuple[ToolCallRecord, ...]:
    """Extract ordered tool call records from turn messages."""
    tool_results = _tool_result_lookup(messages)
    records: list[ToolCallRecord] = []

    for message in messages:
        if message.get("role") != "assistant":
            continue
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            continue
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            if not isinstance(function, dict):
                function = {}
            name = str(function.get("name") or tool_call.get("name") or "")
            if not name:
                continue
            tool_call_id = str(tool_call.get("id") or "")
            arguments_raw = function.get("arguments")
            if isinstance(arguments_raw, str) and arguments_raw.strip().startswith("{"):
                try:
                    arguments_raw = json.loads(arguments_raw)
                except json.JSONDecodeError:
                    pass
            result_message = tool_results.get(tool_call_id) if tool_call_id else None
            content = result_message.get("content") if result_message else None
            records.append(
                ToolCallRecord(
                    name=name,
                    args_summary=_summarize_tool_arguments(arguments_raw),
                    ok=not _is_tool_error(content),
                )
            )
    return tuple(records)


def count_assistant_iterations(messages: Sequence[dict[str, Any]]) -> int:
    """Count assistant messages produced during the turn."""
    return sum(1 for message in messages if message.get("role") == "assistant")


def build_turn_trace(
    *,
    session_key: str,
    query: str,
    messages: Sequence[dict[str, Any]],
    stop_reason: str,
    skills_injected: Sequence[str] = (),
    tools_used: Sequence[str] | None = None,
    turn_id: str = "",
    trace_id: str | None = None,
    token_usage: Mapping[str, int] | None = None,
    baseline_len: int | None = None,
) -> TurnTrace:
    """Build a ``TurnTrace`` from one agent run's messages and metadata."""
    turn_messages = (
        slice_turn_messages(messages, baseline_len)
        if baseline_len is not None
        else list(messages)
    )
    tool_calls = parse_tool_calls_from_messages(turn_messages)
    tool_call_count = len(tools_used) if tools_used is not None else len(tool_calls)
    usage_items = tuple(token_usage.items()) if token_usage else ()
    kwargs: dict[str, Any] = {
        "session_key": session_key,
        "query": query.strip(),
        "turn_id": turn_id,
        "skills_injected": tuple(str(name) for name in skills_injected),
        "tool_calls": tool_calls,
        "tool_call_count": tool_call_count,
        "iterations": count_assistant_iterations(turn_messages),
        "stop_reason": stop_reason,
        "outcome": infer_outcome(stop_reason),
        "token_usage": usage_items,
    }
    if trace_id is not None:
        kwargs["trace_id"] = trace_id
    return TurnTrace(**kwargs)


class TraceRecorder:
    """Persist turn traces when evolution recording is enabled."""

    def __init__(self, workspace: Any, config: EvolutionConfig) -> None:
        from pathlib import Path

        self._config = config
        self._store = TraceStore(Path(workspace))

    @property
    def store(self) -> TraceStore:
        return self._store

    def record(self, trace: TurnTrace) -> bool:
        """Insert *trace* when recording is enabled. Returns True if stored."""
        if not self._config.recording_enabled():
            return False
        self._store.insert(trace)
        pruned = self._store.prune(self._config.trace.retention_days)
        if pruned:
            logger.debug("TraceRecorder pruned {} stale trace(s)", pruned)
        logger.info(
            "TraceRecorder stored trace_id={} session={} tool_calls={} outcome={}",
            trace.trace_id,
            trace.session_key,
            trace.tool_call_count,
            trace.outcome,
        )
        return True

    def record_turn(
        self,
        *,
        session_key: str,
        query: str,
        messages: Sequence[dict[str, Any]],
        stop_reason: str,
        skills_injected: Sequence[str] = (),
        tools_used: Sequence[str] | None = None,
        turn_id: str = "",
        token_usage: Mapping[str, int] | None = None,
        baseline_len: int | None = None,
    ) -> TurnTrace | None:
        """Build and optionally persist a trace for one completed turn."""
        trace = build_turn_trace(
            session_key=session_key,
            query=query,
            messages=messages,
            stop_reason=stop_reason,
            skills_injected=skills_injected,
            tools_used=tools_used,
            turn_id=turn_id,
            token_usage=token_usage,
            baseline_len=baseline_len,
        )
        if not self.record(trace):
            return None
        return trace

    def close(self) -> None:
        self._store.close()
