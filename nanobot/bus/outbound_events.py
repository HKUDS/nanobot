"""Typed outbound events carried by :class:`OutboundMessage`.

The message bus still transports :class:`nanobot.bus.events.OutboundMessage`
because channels need chat routing fields. Runtime/UI semantics live on the
message's explicit ``event`` field rather than in reserved metadata flags.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from nanobot.bus.events import OutboundMessage


class OutboundEvent:
    """Marker base for internal outbound runtime events."""


@dataclass(frozen=True)
class ProgressEvent(OutboundEvent):
    content: str = ""
    tool_hint: bool = False
    reasoning: bool = False
    reasoning_delta: bool = False
    reasoning_end: bool = False
    stream_id: str | None = None
    tool_events: list[dict[str, Any]] | None = None
    file_edit_events: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class RetryWaitEvent(OutboundEvent):
    content: str = ""


@dataclass(frozen=True)
class StreamDeltaEvent(OutboundEvent):
    content: str = ""
    stream_id: str | None = None


@dataclass(frozen=True)
class StreamEndEvent(OutboundEvent):
    content: str = ""
    stream_id: str | None = None
    resuming: bool = False


@dataclass(frozen=True)
class StreamedResponseEvent(OutboundEvent):
    pass


@dataclass(frozen=True)
class TurnEndEvent(OutboundEvent):
    latency_ms: int | None = None
    goal_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class GoalStatusEvent(OutboundEvent):
    status: str
    started_at: float | None = None


@dataclass(frozen=True)
class GoalStateSyncEvent(OutboundEvent):
    goal_state: dict[str, Any]


@dataclass(frozen=True)
class SessionUpdatedEvent(OutboundEvent):
    scope: str | None = None


@dataclass(frozen=True)
class RuntimeModelUpdatedEvent(OutboundEvent):
    model: str | None
    model_preset: str | None = None


@dataclass(frozen=True)
class TurnModelRoutedEvent(OutboundEvent):
    model: str
    model_preset: str | None = None
    task_kind: str = "chat"
    task_type: str | None = None
    complexity: str | None = None
    ephemeral: bool = True


def outbound_message_for_event(
    *,
    channel: str,
    chat_id: str,
    event: OutboundEvent,
    content: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OutboundMessage:
    """Build an :class:`OutboundMessage` for a typed event."""

    return OutboundMessage(
        channel=channel,
        chat_id=chat_id,
        content=_event_content(event) if content is None else content,
        event=event,
        metadata=dict(metadata or {}),
    )


def outbound_event_from_message(msg: OutboundMessage) -> OutboundEvent | None:
    """Return the typed outbound event carried by *msg*, if any."""

    if msg.event is not None:
        return msg.event
    return _legacy_event_from_metadata(msg)


def replace_outbound_event(
    msg: OutboundMessage,
    event: OutboundEvent,
    *,
    content: str | None = None,
) -> OutboundMessage:
    """Return *msg* with a new event and optional content."""

    return replace(
        msg,
        content=_event_content(event) if content is None else content,
        event=event,
    )


def _event_content(event: OutboundEvent) -> str:
    if isinstance(event, ProgressEvent | RetryWaitEvent | StreamDeltaEvent | StreamEndEvent):
        return event.content
    return ""


def _legacy_event_from_metadata(msg: OutboundMessage) -> OutboundEvent | None:
    """Bridge pre-typed outbound metadata flags into typed events.

    New code should set ``OutboundMessage.event`` directly. The fallback keeps
    older in-process extensions and channel plugins from losing runtime events
    while they migrate off reserved metadata flags.
    """

    meta = msg.metadata or {}
    if meta.get("_runtime_model_updated"):
        return RuntimeModelUpdatedEvent(
            model=_metadata_str(meta, "model"),
            model_preset=_metadata_str(meta, "model_preset"),
        )
    if meta.get("_goal_state_sync"):
        goal_state = meta.get("goal_state")
        return GoalStateSyncEvent(goal_state if isinstance(goal_state, dict) else {"active": False})
    if meta.get("_goal_status"):
        status = meta.get("goal_status")
        if not isinstance(status, str) or not status:
            return None
        return GoalStatusEvent(
            status=status,
            started_at=_metadata_float(meta, "started_at", "goal_started_at"),
        )
    if meta.get("_turn_end"):
        goal_state = meta.get("goal_state")
        return TurnEndEvent(
            latency_ms=_metadata_int(meta, "latency_ms"),
            goal_state=goal_state if isinstance(goal_state, dict) else None,
        )
    if meta.get("_session_updated"):
        return SessionUpdatedEvent(scope=_metadata_str(meta, "_session_update_scope"))
    if meta.get("_retry_wait"):
        return RetryWaitEvent(content=msg.content)
    if meta.get("_stream_end"):
        return StreamEndEvent(
            content=msg.content,
            stream_id=_metadata_str(meta, "_stream_id"),
            resuming=bool(meta.get("_resuming")),
        )
    if meta.get("_stream_delta"):
        return StreamDeltaEvent(
            content=msg.content,
            stream_id=_metadata_str(meta, "_stream_id"),
        )
    if meta.get("_streamed"):
        return StreamedResponseEvent()
    if (
        meta.get("_progress")
        or meta.get("_reasoning_delta")
        or meta.get("_reasoning_end")
        or meta.get("_reasoning")
        or meta.get("_file_edit_events")
        or meta.get("_tool_events")
    ):
        tool_events = meta.get("_tool_events")
        file_edit_events = meta.get("_file_edit_events")
        return ProgressEvent(
            content=msg.content,
            tool_hint=bool(meta.get("_tool_hint")),
            reasoning=bool(meta.get("_reasoning")),
            reasoning_delta=bool(meta.get("_reasoning_delta")),
            reasoning_end=bool(meta.get("_reasoning_end")),
            stream_id=_metadata_str(meta, "_stream_id"),
            tool_events=tool_events if isinstance(tool_events, list) else None,
            file_edit_events=file_edit_events if isinstance(file_edit_events, list) else None,
        )
    return None


def _metadata_str(meta: Mapping[str, Any], key: str) -> str | None:
    value = meta.get(key)
    return value if isinstance(value, str) and value else None


def _metadata_int(meta: Mapping[str, Any], key: str) -> int | None:
    value = meta.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _metadata_float(meta: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = meta.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
    return None
