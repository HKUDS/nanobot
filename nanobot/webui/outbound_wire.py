from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypeAlias, TypedDict, cast

from nanobot.bus.outbound_events import (
    ContextCompactionEvent,
    RecoveryStateEvent,
    RetryStatusEvent,
    TurnEndEvent,
)
from nanobot.events import AgentEvent, CompactionReason
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY

_JSONValue: TypeAlias = (
    str | int | float | bool | None | list["_JSONValue"] | dict[str, "_JSONValue"]
)

_TOOL_EVENT_BINARY_OMISSION = "[binary content omitted from WebUI]"


def _is_base64_data_url(value: str) -> bool:
    candidate = value.lstrip()
    return candidate[:5].casefold() == "data:" and ";base64," in candidate[:256].casefold()


def _project_tool_event_value(value: object) -> _JSONValue:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if _is_base64_data_url(value):
            return _TOOL_EVENT_BINARY_OMISSION
        return value
    if isinstance(value, dict):
        data = cast(dict[object, object], value)
        return {
            str(key): _project_tool_event_value(item)
            for key, item in data.items()
        }
    if isinstance(value, list):
        return [_project_tool_event_value(item) for item in cast(list[object], value)]
    if isinstance(value, tuple):
        return [_project_tool_event_value(item) for item in cast(tuple[object, ...], value)]
    return str(value)


def project_tool_events(events: list[dict[str, Any]]) -> list[dict[str, _JSONValue]]:
    """Build WebUI-safe tool events without mutating model-facing results."""
    projected_events: list[dict[str, _JSONValue]] = []
    for event in events:
        projected = _project_tool_event_value(cast(object, event))
        if not isinstance(projected, dict):
            continue
        projected_events.append(projected)
    return projected_events


class _ChatWirePayload(TypedDict):
    chat_id: str
    turn_id: NotRequired[str]


class RecoveryStateWirePayload(_ChatWirePayload):
    event: Literal["recovery_state"]
    status: str
    recovery_id: str
    attempts: int
    reason: NotRequired[str]
    can_continue: NotRequired[bool]
    failure_error_kind: NotRequired[str]
    reply_preserved: NotRequired[bool]


class RetryStatusWirePayload(_ChatWirePayload):
    event: Literal["retry_status"]
    state: str
    attempt: int
    max_attempts: NotRequired[int]
    error_kind: str
    retry_after_s: NotRequired[float]


class TurnEndWirePayload(_ChatWirePayload):
    event: Literal["turn_end"]
    latency_ms: NotRequired[int]
    goal_state: NotRequired[dict[str, Any]]
    usage: NotRequired[dict[str, int]]
    round_usages: NotRequired[list[dict[str, int]]]
    context_window_tokens: NotRequired[int]
    outcome: NotRequired[str]
    failure_kind: NotRequired[str]
    failure_error_kind: NotRequired[str]
    failure_attempts: NotRequired[int]
    failure_message: NotRequired[str]


class ContextCompactionWirePayload(_ChatWirePayload):
    event: Literal["context_compaction"]
    compaction_id: str
    phase: Literal["started", "succeeded", "failed", "cancelled"]
    reason: NotRequired[CompactionReason]


class SubagentTaskWirePayload(_ChatWirePayload):
    event: Literal["subagent_task"]
    task: dict[str, object]


class MessageWirePayload(_ChatWirePayload):
    event: Literal["message"]
    text: str
    render_as: NotRequired[Literal["text"]]
    media: NotRequired[list[str]]
    media_urls: NotRequired[list[dict[str, str]]]
    reply_to: NotRequired[str]
    latency_ms: NotRequired[int]
    tool_events: NotRequired[list[dict[str, _JSONValue]]]
    agent_ui: NotRequired[object]
    kind: NotRequired[Literal["tool_hint", "progress"]]


class StreamWirePayload(_ChatWirePayload):
    event: Literal["delta", "stream_end", "reasoning_delta", "reasoning_end"]
    text: NotRequired[str]
    stream_id: NotRequired[str]
    resuming: NotRequired[bool]
    merge_next: NotRequired[bool]


class FileEditWirePayload(_ChatWirePayload):
    event: Literal["file_edit"]
    edits: list[dict[str, Any]]


class GoalStateWirePayload(_ChatWirePayload):
    event: Literal["goal_state"]
    goal_state: dict[str, Any]


class GoalStatusWirePayload(_ChatWirePayload):
    event: Literal["goal_status"]
    status: str
    started_at: NotRequired[float]


class SessionUpdatedWirePayload(_ChatWirePayload):
    event: Literal["session_updated"]
    scope: NotRequired[str]


class UserInputWirePayload(_ChatWirePayload):
    event: Literal["user_message"]
    text: str
    created_at_ms: int
    starts_turn: bool
    provenance: NotRequired[dict[str, Any]]


class PairingChangedWirePayload(TypedDict):
    event: Literal["pairing_changed"]


class RuntimeModelWirePayload(TypedDict):
    event: Literal["runtime_model_updated"]
    model_name: str
    model_preset: NotRequired[str]


class TurnModelWirePayload(_ChatWirePayload):
    event: Literal["turn_model_updated"]
    model_name: str
    model_preset: NotRequired[str]
    context_window_tokens: NotRequired[int]
    fallback: NotRequired[bool]
    reauth_provider: NotRequired[str]


WebUIWirePayload: TypeAlias = (
    RetryStatusWirePayload | ContextCompactionWirePayload | RecoveryStateWirePayload | TurnEndWirePayload
    | SubagentTaskWirePayload | MessageWirePayload | StreamWirePayload | FileEditWirePayload
    | GoalStateWirePayload | GoalStatusWirePayload | SessionUpdatedWirePayload | UserInputWirePayload
    | PairingChangedWirePayload | RuntimeModelWirePayload | TurnModelWirePayload
)
WebUIWirePersistence: TypeAlias = Literal[
    "transient",
    "turn_activity",
    "turn_complete",
]


def encode_recovery_state(
    chat_id: str,
    event: RecoveryStateEvent,
) -> RecoveryStateWirePayload:
    """Project one transient recovery transition onto its stable wire shape."""
    payload: RecoveryStateWirePayload = {
        "event": "recovery_state",
        "chat_id": chat_id,
        "status": event.status,
        "recovery_id": event.recovery_id,
        "attempts": event.attempts,
    }
    if event.reason:
        payload["reason"] = event.reason
    if event.can_continue is not None:
        payload["can_continue"] = event.can_continue
    if event.failure_error_kind is not None:
        payload["failure_error_kind"] = event.failure_error_kind
    if event.reply_preserved is not None:
        payload["reply_preserved"] = event.reply_preserved
    return payload


def encode_context_compaction(
    chat_id: str,
    event: ContextCompactionEvent,
) -> ContextCompactionWirePayload:
    """Project one summary-free compaction transition onto its stable wire shape."""
    payload: ContextCompactionWirePayload = {
        "event": "context_compaction",
        "chat_id": chat_id,
        "compaction_id": event.compaction_id,
        "phase": event.phase,
    }
    if event.reason is not None:
        payload["reason"] = event.reason
    return payload


@dataclass(frozen=True)
class NotificationProjection:
    """Allowlisted public payload and its durability policy."""

    payload: WebUIWirePayload
    persistence: WebUIWirePersistence = "transient"
    deliver_offline: bool = False
    attach_turn_metadata: bool = False


def project_notification(
    chat_id: str, event: AgentEvent | None, metadata: Mapping[str, object] | None = None,
) -> NotificationProjection | None:
    """Keep notification serialization and persistence decisions at one boundary."""
    if isinstance(event, ContextCompactionEvent):
        return NotificationProjection(
            encode_context_compaction(chat_id, event),
            persistence="transient" if event.phase == "started" else "turn_activity",
            deliver_offline=True,
            attach_turn_metadata=True,
        )
    if isinstance(event, RetryStatusEvent):
        return NotificationProjection(encode_retry_status(chat_id, event, metadata))
    if isinstance(event, RecoveryStateEvent):
        return NotificationProjection(encode_recovery_state(chat_id, event))
    return None


def encode_retry_status(
    chat_id: str,
    event: RetryStatusEvent,
    metadata: Mapping[str, object] | None = None,
) -> RetryStatusWirePayload:
    """Project one transient retry transition onto its stable wire shape."""
    payload: RetryStatusWirePayload = {
        "event": "retry_status",
        "chat_id": chat_id,
        "state": event.state,
        "attempt": event.attempt,
        "error_kind": event.error_kind,
    }
    turn_id = (metadata or {}).get(WEBUI_TURN_METADATA_KEY)
    if isinstance(turn_id, str) and turn_id:
        payload["turn_id"] = turn_id
    if event.max_attempts is not None:
        payload["max_attempts"] = event.max_attempts
    if event.next_retry_at is not None:
        payload["retry_after_s"] = max(0.0, event.next_retry_at - time.time())
    return payload
def encode_turn_end(
    chat_id: str,
    event: TurnEndEvent,
    metadata: Mapping[str, object] | None = None,
) -> TurnEndWirePayload:
    """Project a completed turn without leaking internal metadata onto the wire."""
    payload: TurnEndWirePayload = {
        "event": "turn_end",
        "chat_id": chat_id,
    }
    turn_id = (metadata or {}).get(WEBUI_TURN_METADATA_KEY)
    if isinstance(turn_id, str) and turn_id:
        payload["turn_id"] = turn_id
    if event.latency_ms is not None:
        payload["latency_ms"] = int(event.latency_ms)
    if event.goal_state is not None:
        payload["goal_state"] = event.goal_state
    if event.usage is not None:
        payload["usage"] = event.usage.to_turn_dict()
    if event.round_usages:
        payload["round_usages"] = [item.to_turn_dict() for item in event.round_usages]
    if event.context_window_tokens is not None:
        payload["context_window_tokens"] = int(event.context_window_tokens)
    if event.outcome != "completed":
        payload["outcome"] = event.outcome
    if event.failure_kind is not None:
        payload["failure_kind"] = event.failure_kind
    if event.failure_error_kind is not None:
        payload["failure_error_kind"] = event.failure_error_kind
    if event.failure_attempts is not None:
        payload["failure_attempts"] = int(event.failure_attempts)
    if event.failure_message is not None:
        payload["failure_message"] = event.failure_message
    return payload
