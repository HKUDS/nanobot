# nanobot/agent/callbacks.py
"""Typed progress event hierarchy for the agent callback protocol.

Replaces the 8-kwarg ProgressCallback Protocol in loop.py with a proper
discriminated union. Each event type represents exactly one thing that
happened. Consumers match on type; emitters construct typed objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(frozen=True, slots=True)
class TextChunk:
    """Streaming or final text content from the agent."""

    content: str
    streaming: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    """Agent is invoking a tool."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    """Tool has returned a result."""

    tool_call_id: str
    result: str
    tool_name: str = ""


@dataclass(frozen=True, slots=True)
class DelegateStartEvent:
    """Agent is delegating to a child agent."""

    delegation_id: str
    child_role: str
    task_title: str = ""


@dataclass(frozen=True, slots=True)
class DelegateEndEvent:
    """Child agent delegation completed."""

    delegation_id: str
    success: bool


@dataclass(frozen=True, slots=True)
class StatusEvent:
    """Lifecycle signal: thinking, retrying, calling_tool."""

    status_code: str  # "thinking" | "retrying" | "calling_tool"
    label: str = ""


ProgressEvent = (
    TextChunk
    | ToolCallEvent
    | ToolResultEvent
    | DelegateStartEvent
    | DelegateEndEvent
    | StatusEvent
)

ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]

__all__ = [
    "DelegateEndEvent",
    "DelegateStartEvent",
    "ProgressCallback",
    "ProgressEvent",
    "StatusEvent",
    "TextChunk",
    "ToolCallEvent",
    "ToolResultEvent",
]
