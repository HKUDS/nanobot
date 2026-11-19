"""Bounded activity summaries and their unaugmented, replayable detail."""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, NamedTuple, Sequence, TypedDict, cast

from nanobot.webui.transcript_replay import WEBUI_REPLAY_IDENTITY_KEY, parse_replay_identity

_TRACE_CALL_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)\(")
_TRACE_DETAIL_REF_RE = re.compile(r"^(?P<turn>\d{1,12})\.(?P<message>history-[0-9a-f]{20})$")


def parse_trace_detail_ref(value: str) -> tuple[int, str] | None:
    match = _TRACE_DETAIL_REF_RE.fullmatch(value)
    return (int(match.group("turn")), match.group("message")) if match else None


class _ProjectionReceipt(TypedDict):
    turn_id: str
    ranges: list[list[int]]


def _projection_receipts(records: Sequence[Mapping[str, Any]]) -> list[_ProjectionReceipt]:
    members: dict[str, set[int]] = {}
    for record in records:
        turn_id, sequence = record.get("turn_id"), record.get("turn_seq")
        if (
            isinstance(turn_id, str) and turn_id
            and isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 0
        ):
            members.setdefault(turn_id, set()).add(sequence)
    receipts: list[_ProjectionReceipt] = []
    for turn_id, sequences in members.items():
        ranges: list[list[int]] = []
        for sequence in sorted(sequences):
            if ranges and ranges[-1][1] + 1 == sequence:
                ranges[-1][1] = sequence
            else:
                ranges.append([sequence, sequence])
        receipts.append({"turn_id": turn_id, "ranges": ranges})
    return receipts


class _DeferredTraceGroup(NamedTuple):
    start: int
    stop: int
    detail_bytes: int
    trace_count: int


def _format_tool_call_trace(call: Any) -> str | None:
    if not call or not isinstance(call, dict):
        return None
    call_data = cast(dict[str, Any], call)
    fn = call_data.get("function")
    function_data = cast(dict[str, Any], fn) if isinstance(fn, dict) else None
    name = function_data.get("name") if function_data is not None else None
    if not isinstance(name, str) or not name:
        raw_name = call_data.get("name")
        name = raw_name if isinstance(raw_name, str) else ""
    if not name:
        return None
    args = (
        function_data.get("arguments") if function_data is not None else None
    ) or call_data.get("arguments")
    if isinstance(args, str) and args.strip():
        return f"{name}({args})"
    if args and isinstance(args, dict):
        return f"{name}({json.dumps(args, ensure_ascii=False)})"
    return f"{name}()"


def tool_trace_lines_from_events(events: Any) -> list[str]:
    if not isinstance(events, list):
        return []
    lines: list[str] = []
    seen: set[str] = set()
    for event in cast(list[Any], events):
        if not event or not isinstance(event, dict):
            continue
        tool_event = cast(dict[str, Any], event)
        if tool_event.get("phase") not in {"start", "end", "error"}:
            continue
        call_id = tool_event.get("call_id")
        if isinstance(call_id, str) and call_id:
            if call_id in seen:
                continue
            seen.add(call_id)
        t = _format_tool_call_trace(tool_event)
        if t:
            lines.append(t)
    return lines


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[: max_bytes - 3].decode("utf-8", errors="ignore") + "…"


def _trace_summary(line: str) -> str:
    if len(line.encode("utf-8")) <= 512:
        return line
    match = _TRACE_CALL_NAME_RE.match(line.strip())
    return f"{_truncate_utf8(match.group(1), 240)}(…)" if match else _truncate_utf8(line, 240)


class TraceProjection(NamedTuple):
    groups: dict[int, _DeferredTraceGroup]
    events: dict[int, dict[str, Any]]

    def detail(self, message_id: str) -> dict[str, Any] | None:
        for group in self.groups.values():
            if self.events[group.start]["projection_id"] == message_id:
                return {
                    "message_id": message_id,
                    "events": [self.events[i] for i in range(group.start, group.stop) if i in self.events],
                }
        return None

    @staticmethod
    def summarize(
        lines: list[dict[str, Any]], group: _DeferredTraceGroup, event: dict[str, Any],
    ) -> None:
        identity = parse_replay_identity(lines[group.start].get(WEBUI_REPLAY_IDENTITY_KEY))
        detail_ref = f"{identity[0]}.{event['projection_id']}" if identity is not None else None
        last_text = next(
            (
                text
                for grouped in reversed(lines[group.start:group.stop])
                if isinstance((text := grouped.get("text")), str) and text
            ),
            "",
        )
        event["text"] = _trace_summary(last_text)
        event.pop("tool_events", None)
        receipts = _projection_receipts([
            grouped for grouped in lines[group.start:group.stop]
            if grouped.get("event") != "model_request"
        ])
        if receipts:
            event["projection_receipts"] = receipts
        if detail_ref is not None:
            event["trace_detail"] = {
                "ref": detail_ref,
                "bytes": group.detail_bytes,
                "traceCount": group.trace_count,
            }


def index_trace_projection(
    lines: list[dict[str, Any]],
    project: Callable[[dict[str, Any]], dict[str, Any] | None],
    *,
    max_inline_bytes: int,
) -> TraceProjection:
    groups: dict[int, _DeferredTraceGroup] = {}
    preprojected: dict[int, dict[str, Any]] = {}
    start: int | None = None
    detail_bytes = 0
    trace_count = 0

    def flush(stop: int) -> None:
        nonlocal start, detail_bytes, trace_count
        if (
            start is not None
            and detail_bytes > max_inline_bytes
        ):
            groups[start] = _DeferredTraceGroup(
                start=start,
                stop=stop,
                detail_bytes=detail_bytes,
                trace_count=max(1, trace_count),
            )
        start = None
        detail_bytes = 0
        trace_count = 0

    for index, record in enumerate(lines):
        # Usage belongs to the turn, not the activity body. It must not split
        # one deferred tool group into many eagerly loaded fragments.
        if record.get("event") == "model_request":
            continue
        is_activity = (
            record.get("event") == "message"
            and record.get("kind") in {"tool_hint", "progress"}
        )
        if not is_activity:
            flush(index)
            continue
        event = project(record)
        if event is None:
            flush(index)
            continue
        preprojected[index] = event
        if start is None:
            start = index
        detail_bytes += len(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        tool_events = cast(list[dict[str, Any]], event.get("tool_events") or [])
        traces = tool_trace_lines_from_events(tool_events)
        if traces:
            trace_count += len(traces)
        elif not tool_events and isinstance(record.get("text"), str) and record["text"]:
            trace_count += 1
    flush(len(lines))
    return TraceProjection(groups, preprojected)
