"""Typed event dataclasses for HookCenter lifecycle events.

Each hook point in the agent lifecycle is represented by a typed dataclass.
Handlers subscribe by event type; HookCenter dispatches by ``type(event)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.providers.base import LLMResponse, ToolCallRequest


@dataclass(slots=True)
class BeforeIteration:
    iteration: int
    messages: list[dict[str, Any]]


@dataclass(slots=True)
class OnStream:
    delta: str
    iteration: int


@dataclass(slots=True)
class OnStreamEnd:
    resuming: bool
    iteration: int


@dataclass(slots=True)
class BeforeExecuteTools:
    iteration: int
    tool_calls: list["ToolCallRequest"]
    response: "LLMResponse | None" = None


@dataclass(slots=True)
class AfterIteration:
    iteration: int
    final_content: str | None = None
    stop_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list["ToolCallRequest"] = field(default_factory=list)
    tool_events: list[dict[str, str]] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class FinalizeContent:
    """Registration-type marker for finalize_content pipeline handlers.

    Not dispatched through emit().  HookCenter.finalize_content() collects
    handlers registered under this type and runs them as a sync pipeline.
    """
    content: str | None
    context: Any = None
