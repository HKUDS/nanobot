"""Structured progress-event helpers shared by agent runtimes."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, cast

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.tools.base import ToolResult
from nanobot.bus.outbound_events import (
    FileEditEvent,
    ProgressEvent,
    StreamDeltaEvent,
    StreamEndEvent,
)
from nanobot.events import NO_EVENTS, AgentEvent, EventSink


def _on_progress_accepts(cb: Callable[..., Any], name: str) -> bool:
    try:
        sig = inspect.signature(cb)
    except (TypeError, ValueError):
        return False
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return True
    return name in sig.parameters


def output_events(
    *,
    default: EventSink = NO_EVENTS,
    on_progress: Callable[..., Awaitable[None]] | None = None,
    on_stream: Callable[[str], Awaitable[None]] | None = None,
    on_stream_end: Callable[..., Awaitable[None]] | None = None,
) -> EventSink:
    """Adapt direct-call output callbacks once, outside the runner and hooks."""
    if on_progress is None and on_stream is None and on_stream_end is None:
        return default
    progress_fields = {
        name for name in ("tool_events", "file_edit_events", "reasoning", "reasoning_end")
        if on_progress is not None and _on_progress_accepts(on_progress, name)
    }
    merge_next = on_stream_end is not None and _on_progress_accepts(on_stream_end, "merge_next")

    def accepts(event_type: type[AgentEvent]) -> bool:
        if issubclass(event_type, FileEditEvent) and on_progress is not None:
            return "file_edit_events" in progress_fields
        if issubclass(event_type, ProgressEvent) and on_progress is not None:
            return True
        if issubclass(event_type, StreamDeltaEvent) and on_stream is not None:
            return True
        if issubclass(event_type, StreamEndEvent) and on_stream_end is not None:
            return True
        return default.accepts(event_type)

    async def publish(event: AgentEvent) -> None:
        if isinstance(event, ProgressEvent) and on_progress is not None:
            if event.file_edit_events:
                if "file_edit_events" in progress_fields:
                    await on_progress(event.content, file_edit_events=event.file_edit_events)
                return
            if event.reasoning_delta or event.reasoning_end:
                name = "reasoning" if event.reasoning_delta else "reasoning_end"
                if name in progress_fields:
                    await on_progress(event.content, **{name: True})
                return
            if event.tool_events and not event.tool_hint and "tool_events" not in progress_fields:
                return
            kwargs: dict[str, Any] = {"tool_hint": event.tool_hint}
            if event.tool_events and "tool_events" in progress_fields:
                kwargs["tool_events"] = event.tool_events
            await on_progress(event.content, **kwargs)
        elif isinstance(event, StreamDeltaEvent) and on_stream is not None:
            await on_stream(event.content)
        elif isinstance(event, StreamEndEvent) and on_stream_end is not None:
            kwargs = {"resuming": event.resuming}
            if event.merge_next and merge_next:
                kwargs["merge_next"] = True
            await on_stream_end(**kwargs)
        elif default.publish is not None:
            await default.publish(event)

    return EventSink(publish, accepts)


def _tool_event_arguments(tool_call: Any) -> dict[str, Any]:
    arguments = getattr(tool_call, "arguments", {}) or {}
    return cast(dict[str, Any], arguments) if isinstance(arguments, dict) else {}


def build_tool_event_start_payload(tool_call: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "phase": "start",
        "call_id": str(getattr(tool_call, "id", "") or ""),
        "name": getattr(tool_call, "name", ""),
        "arguments": _tool_event_arguments(tool_call),
        "result": None,
        "error": None,
        "files": [],
        "embeds": [],
    }


def tool_event_result_extras(result: Any) -> tuple[list[Any], list[Any]]:
    if not isinstance(result, dict):
        return [], []
    result_data = cast(dict[str, Any], result)
    raw_files = result_data.get("files")
    raw_embeds = result_data.get("embeds")
    files: list[Any] = cast(list[Any], raw_files) if isinstance(raw_files, list) else []
    embeds: list[Any] = cast(list[Any], raw_embeds) if isinstance(raw_embeds, list) else []
    return files, embeds


def tool_event_result_data(result: Any) -> dict[str, Any] | None:
    """Return structured UI data without changing the model-facing tool result."""
    if isinstance(result, ToolResult):
        return result.data
    return None


def build_tool_event_finish_payloads(context: AgentHookContext) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    count = min(len(context.tool_calls), len(context.tool_results), len(context.tool_events))
    for idx in range(count):
        tool_call = context.tool_calls[idx]
        result = context.tool_results[idx]
        event = context.tool_events[idx]
        status = event.get("status")
        phase = "end" if status == "ok" else "error"
        files, embeds = tool_event_result_extras(result)
        data = tool_event_result_data(result)
        payload = {
            "version": 1,
            "phase": phase,
            "call_id": str(getattr(tool_call, "id", "") or ""),
            "name": getattr(tool_call, "name", ""),
            "arguments": _tool_event_arguments(tool_call),
            "result": result if phase == "end" else None,
            "error": None,
            "files": files,
            "embeds": embeds,
        }
        if data is not None:
            payload["data"] = data
        if phase == "error":
            if isinstance(result, str) and result.strip():
                payload["error"] = result.strip()
            else:
                payload["error"] = str(event.get("detail") or "Tool execution failed")
        payloads.append(payload)
    return payloads
