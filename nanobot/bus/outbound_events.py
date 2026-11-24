"""Typed outbound events carried by :class:`OutboundMessage`.

The message bus still transports :class:`nanobot.bus.events.OutboundMessage`
because channels need chat routing fields. Runtime/UI semantics live on the
message's explicit ``event`` field rather than in reserved metadata flags.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, NotRequired, TypedDict

from nanobot.bus.events import OutboundMessage
from nanobot.command_copy import command_text
from nanobot.events import AgentEvent
from nanobot.events import ContextCompactionEvent as ContextCompactionEvent
from nanobot.events import RecoveryStateEvent as RecoveryStateEvent
from nanobot.events import RetryStatusEvent as RetryStatusEvent
from nanobot.events import RetryWaitEvent as RetryWaitEvent
from nanobot.providers.base import LLMUsage


@dataclass(frozen=True)
class ProgressEvent(AgentEvent):
    content: str = ""
    tool_hint: bool = False
    reasoning: bool = False
    reasoning_delta: bool = False
    reasoning_end: bool = False
    stream_id: str | None = None
    tool_events: list[dict[str, Any]] | None = None
    file_edit_events: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class FileEditEvent(ProgressEvent):
    """File activity whose snapshot collection requires an interested consumer."""


@dataclass(frozen=True)
class StreamDeltaEvent(AgentEvent):
    content: str = ""
    stream_id: str | None = None


@dataclass(frozen=True)
class StreamEndEvent(AgentEvent):
    content: str = ""
    stream_id: str | None = None
    resuming: bool = False
    merge_next: bool = False


@dataclass(frozen=True)
class StreamedResponseEvent(AgentEvent):
    pass


@dataclass(frozen=True)
class SideChannelReplyEvent(AgentEvent):
    """Command text that does not replace the active assistant answer."""

    notification_id: str | None = None


class CommandLine(TypedDict):
    key: str
    values: dict[str, str | int | float]
    prefix: NotRequired[str]  # Literal syntax displayed beside a translated description.


class LiteralLine(TypedDict):
    text: str


CommandPart = CommandLine | LiteralLine
CommandOutcome = Literal["stopped", "session_reset"]


@dataclass(frozen=True, kw_only=True)
class CommandResultEvent(SideChannelReplyEvent):
    """A slash-command outcome; the receiving channel chooses whether and how to display it."""

    command: str
    parts: tuple[CommandPart, ...]
    outcome: CommandOutcome | None = None
    switched_preset: str | None = None


@dataclass(frozen=True)
class TurnEndEvent(AgentEvent):
    latency_ms: int | None = None
    goal_state: dict[str, Any] | None = None
    usage: LLMUsage | None = None
    round_usages: tuple[LLMUsage, ...] = ()
    context_window_tokens: int | None = None
    outcome: str = "completed"
    failure_kind: str | None = None
    failure_error_kind: str | None = None
    failure_attempts: int | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class GoalStatusEvent(AgentEvent):
    status: str
    started_at: float | None = None


@dataclass(frozen=True)
class GoalStateSyncEvent(AgentEvent):
    goal_state: dict[str, Any]


@dataclass(frozen=True)
class SessionUpdatedEvent(AgentEvent):
    scope: str | None = None


@dataclass(frozen=True)
class UserInputEvent(AgentEvent):
    """A user-input row projected by an edge adapter."""

    content: str
    created_at_ms: int
    input_id: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class RuntimeModelUpdatedEvent(AgentEvent):
    model: str | None
    model_preset: str | None = None


@dataclass(frozen=True)
class TurnModelUpdatedEvent(AgentEvent):
    """The canonical preset and concrete model handling one chat turn."""

    model: str
    model_preset: str | None = None
    context_window_tokens: int | None = None
    fallback: bool = False
    reauth_provider: str | None = None


def outbound_message_for_event(
    *,
    channel: str,
    chat_id: str,
    event: AgentEvent,
    content: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OutboundMessage:
    """Build an :class:`OutboundMessage` for a typed event."""

    return OutboundMessage(
        channel=channel,
        chat_id=chat_id,
        content=_event_content(event, (metadata or {}).get("locale")) if content is None else content,
        event=event,
        metadata=dict(metadata or {}),
    )


def replace_outbound_event(
    msg: OutboundMessage,
    event: AgentEvent,
    *,
    content: str | None = None,
) -> OutboundMessage:
    """Return *msg* with a new event and optional content."""

    return replace(
        msg,
        content=_event_content(event, msg.metadata.get("locale")) if content is None else content,
        event=event,
    )


def _event_content(event: AgentEvent, locale: object) -> str:
    if isinstance(
        event,
        ProgressEvent | RetryWaitEvent | StreamDeltaEvent | StreamEndEvent | UserInputEvent,
    ):
        return event.content
    if isinstance(event, ContextCompactionEvent):
        return command_text(f"compact.{event.phase}", locale)
    return ""
