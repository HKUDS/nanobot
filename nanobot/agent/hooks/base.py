"""Base classes for the event-driven hook system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class HookEvent(str, Enum):
    """Lifecycle events that hooks can listen to."""

    # Session lifecycle
    SESSION_START = "SessionStart"

    # Tool execution
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"

    # Context building
    PRE_BUILD_CONTEXT = "PreBuildContext"

    # Agent stop
    STOP = "Stop"


@dataclass
class HookResult:
    """Result returned by a hook after processing an event.

    - proceed: True to continue, False to block (short-circuits remaining hooks).
    - reason: Explanation when blocking.
    - modified_data: Transformed payload (e.g. filtered skills list).
    """

    proceed: bool = True
    reason: str = ""
    modified_data: Any = None


class Hook(ABC):
    """Base class for event-driven hooks."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique hook identifier."""
        ...

    @property
    def priority(self) -> int:
        """Execution order (lower = earlier). Default: 100."""
        return 100

    @property
    def matcher(self) -> str | None:
        """Regex pattern for PreToolUse/PostToolUse tool-name filtering.

        None means match all events (no filtering).
        """
        return None

    def on_event(self, event: HookEvent, context: dict) -> HookResult:
        """Handle an event. Override in subclasses."""
        return HookResult()
