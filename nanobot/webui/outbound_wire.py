"""Encode typed outbound events for the WebUI wire protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypeAlias, TypedDict

from nanobot.bus.outbound_events import (
    ContextCompactionEvent,
    RecoveryStateEvent,
    TurnEndEvent,
)
from nanobot.events import AgentEvent
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY


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


class TurnEndWirePayload(_ChatWirePayload):
    event: Literal["turn_end"]
    latency_ms: NotRequired[int]
    goal_state: NotRequired[dict[str, Any]]
    usage: NotRequired[dict[str, int]]
    round_usages: NotRequired[list[dict[str, int]]]
    context_window_tokens: NotRequired[int]


class ContextCompactionWirePayload(_ChatWirePayload):
    event: Literal["context_compaction"]
    compaction_id: str
    phase: Literal["started", "succeeded", "failed", "cancelled"]


WebUIWirePayload: TypeAlias = (
    ContextCompactionWirePayload | RecoveryStateWirePayload | TurnEndWirePayload
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
    return payload


@dataclass(frozen=True)
class NotificationProjection:
    """Allowlisted public payload and its durability policy."""

    payload: WebUIWirePayload
    persistence: WebUIWirePersistence = "transient"
    deliver_offline: bool = False
    attach_turn_metadata: bool = False


def project_notification(chat_id: str, event: AgentEvent | None) -> NotificationProjection | None:
    """Keep notification serialization and persistence decisions at one boundary."""
    if isinstance(event, ContextCompactionEvent):
        return NotificationProjection(
            encode_context_compaction(chat_id, event),
            persistence="transient" if event.phase == "started" else "turn_activity",
            deliver_offline=True,
            attach_turn_metadata=True,
        )
    if isinstance(event, RecoveryStateEvent):
        return NotificationProjection(encode_recovery_state(chat_id, event))
    return None


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
    return payload
