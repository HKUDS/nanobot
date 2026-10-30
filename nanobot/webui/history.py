from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nanobot.bus.events import INBOUND_META_LOCAL_MEDIA
from nanobot.session.display_history import HistoryFact, HistoryKind, HistoryReader
from nanobot.webui.session_identity import webui_chat_id

_EVENTS = {
    "user": HistoryKind.INPUT,
    "message": HistoryKind.ANSWER,
    "stream_end": HistoryKind.ANSWER_SEGMENT,
    "reasoning_end": HistoryKind.REASONING_SEGMENT,
    "file_edit": HistoryKind.FILE_ACTIVITY,
    "turn_end": HistoryKind.COMPLETION,
    "fork_marker": HistoryKind.FORK_BOUNDARY,
    "context_compaction": HistoryKind.COMPACTION,
    "delta": HistoryKind.ANSWER_FRAGMENT,
    "reasoning_delta": HistoryKind.REASONING_FRAGMENT,
}
_MESSAGE_KINDS = {
    "reasoning": HistoryKind.REASONING,
    "progress": HistoryKind.PROGRESS,
    "tool_hint": HistoryKind.TOOL_ACTIVITY,
}
_CONTENT_FIELDS = frozenset({
    "text", "media_paths", "media", "media_urls", "reply_to", "agent_ui", "cli_apps", "mcp_presets", "session_mentions",
    "session_message", INBOUND_META_LOCAL_MEDIA, "tool_events", "edits", "source", "response_sources", "resuming",
    "merge_next", "latency_ms", "usage", "round_usages", "context_window_tokens", "goal_state",
    "outcome", "failure_kind", "failure_error_kind", "failure_attempts", "failure_message",
    "transcript_incomplete", "stream_id", "compaction_id", "phase", "reason", "render_as",
})


def fact_from_record(record: Mapping[str, Any]) -> HistoryFact:
    """Parse the channel boundary once; core storage never sees event/chat_id keys."""
    event = record.get("event")
    if event not in _EVENTS:
        raise ValueError(f"unsupported history event: {event!r}")
    kind = _EVENTS[event]
    if event == "message":
        message_kind = record.get("kind")
        if message_kind is not None and message_kind not in _MESSAGE_KINDS:
            raise ValueError(f"unsupported history message kind: {message_kind!r}")
        if isinstance(message_kind, str):
            kind = _MESSAGE_KINDS[message_kind]
    created = record.get("created_at_ms", 0)
    if isinstance(created, bool) or not isinstance(created, int | float) or not 0 <= created < 10**16:
        raise ValueError("invalid history timestamp")
    sequence = record.get("turn_seq")
    if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0):
        raise ValueError("invalid history sequence")
    turn_id, phase = record.get("turn_id"), record.get("turn_phase")
    if turn_id is not None and (not isinstance(turn_id, str) or len(turn_id) > 128):
        raise ValueError("invalid history turn identity")
    if phase is not None and not isinstance(phase, str):
        raise ValueError("invalid history phase")
    fact = HistoryFact(kind, {key: value for key, value in record.items() if key in _CONTENT_FIELDS},
                       turn_id, phase, sequence, int(created))
    return fact


def record_from_fact(fact: HistoryFact, key: str) -> dict[str, Any]:
    if fact.kind in _MESSAGE_KINDS.values():
        event = "message"
        message_kind = next(name for name, kind in _MESSAGE_KINDS.items() if kind is fact.kind)
    else:
        event = next(name for name, kind in _EVENTS.items() if kind is fact.kind)
        message_kind = None
    record = {"event": event, "chat_id": webui_chat_id(key), **fact.content,
              "created_at_ms": fact.created_at_ms}
    if message_kind:
        record["kind"] = message_kind
    if fact.turn_id is not None:
        record["turn_id"] = fact.turn_id
    if fact.phase is not None:
        record["turn_phase"] = fact.phase
    if fact.sequence is not None:
        record["turn_seq"] = fact.sequence
    return record


def turn_records(
    history: HistoryReader, ordinal: int, *, max_records: int | None = None, max_bytes: int | None = None,
) -> list[dict[str, Any]]:
    return [{**record_from_fact(fact, history.key),
             "_webui_replay_identity": f"turn:{ordinal}:record:{position}"}
            for position, fact in history.read_entries(ordinal, max_records=max_records, max_bytes=max_bytes)]
