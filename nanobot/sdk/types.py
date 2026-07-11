"""Public SDK value objects and event constants."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, TypeAlias

from nanobot.runtime_context import public_history_messages

StreamEventType: TypeAlias = Literal[
    "run.started",
    "text.delta",
    "text.completed",
    "reasoning.delta",
    "reasoning.completed",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "run.completed",
    "run.failed",
]

STREAM_EVENT_RUN_STARTED: StreamEventType = "run.started"
STREAM_EVENT_TEXT_DELTA: StreamEventType = "text.delta"
STREAM_EVENT_TEXT_COMPLETED: StreamEventType = "text.completed"
STREAM_EVENT_REASONING_DELTA: StreamEventType = "reasoning.delta"
STREAM_EVENT_REASONING_COMPLETED: StreamEventType = "reasoning.completed"
STREAM_EVENT_TOOL_STARTED: StreamEventType = "tool.started"
STREAM_EVENT_TOOL_COMPLETED: StreamEventType = "tool.completed"
STREAM_EVENT_TOOL_FAILED: StreamEventType = "tool.failed"
STREAM_EVENT_RUN_COMPLETED: StreamEventType = "run.completed"
STREAM_EVENT_RUN_FAILED: StreamEventType = "run.failed"

STREAM_EVENT_TYPES: tuple[StreamEventType, ...] = (
    STREAM_EVENT_RUN_STARTED,
    STREAM_EVENT_TEXT_DELTA,
    STREAM_EVENT_TEXT_COMPLETED,
    STREAM_EVENT_REASONING_DELTA,
    STREAM_EVENT_REASONING_COMPLETED,
    STREAM_EVENT_TOOL_STARTED,
    STREAM_EVENT_TOOL_COMPLETED,
    STREAM_EVENT_TOOL_FAILED,
    STREAM_EVENT_RUN_COMPLETED,
    STREAM_EVENT_RUN_FAILED,
)


@dataclass(slots=True)
class RunResult:
    """Result of a single agent run."""

    content: str
    tools_used: list[str] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StreamEvent:
    """A typed event emitted by ``Nanobot.stream()`` and ``RunStream``."""

    type: StreamEventType
    delta: str = ""
    content: str = ""
    result: RunResult | None = None
    name: str | None = None
    tool_call_id: str | None = None
    arguments: dict[str, Any] | None = None
    iteration: int | None = None
    resuming: bool | None = None
    usage: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionSnapshot:
    """A durable snapshot of one nanobot session."""

    key: str
    messages: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable copy of the snapshot."""
        return {
            "key": self.key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": deepcopy(self.metadata),
            "messages": deepcopy(self.messages),
        }


@dataclass(slots=True)
class SessionInfo:
    """Compact session metadata for listings."""

    key: str
    created_at: str | None = None
    updated_at: str | None = None
    title: str = ""
    preview: str = ""
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable copy of the listing row."""
        return {
            "key": self.key,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "title": self.title,
            "preview": self.preview,
            "path": self.path,
        }


def snapshot_from_session(session: Any) -> SessionSnapshot:
    return SessionSnapshot(
        key=session.key,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
        metadata=deepcopy(session.metadata),
        messages=public_history_messages(session.messages),
    )


def snapshot_from_payload(payload: Mapping[str, Any]) -> SessionSnapshot:
    return SessionSnapshot(
        key=str(payload.get("key") or ""),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
        metadata=deepcopy(dict(payload.get("metadata") or {})),
        messages=public_history_messages(
            message
            for message in list(payload.get("messages") or [])
            if isinstance(message, Mapping)
        ),
    )


def result_from_response(response: Any, capture: Any) -> RunResult:
    content = (response.content if response else None) or ""
    metadata = dict(response.metadata) if response and response.metadata else {}
    return RunResult(
        content=content,
        tools_used=capture.tools_used,
        messages=capture.messages,
        usage=capture.usage,
        stop_reason=capture.stop_reason,
        error=capture.error,
        metadata=metadata,
    )
