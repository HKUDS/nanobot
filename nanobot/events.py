"""Transport-independent notifications emitted by agent operations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from loguru import logger


class AgentEvent:
    """A typed event; only explicitly projected events cross a client boundary."""


@dataclass(frozen=True)
class ContextCompactionEvent(AgentEvent):
    compaction_id: str
    phase: Literal["started", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True)
class RetryWaitEvent(AgentEvent):
    content: str = ""


@dataclass(frozen=True)
class RecoveryStateEvent(AgentEvent):
    status: str
    recovery_id: str
    reason: str | None = None
    attempts: int = 0
    can_continue: bool | None = None


@dataclass(frozen=True)
class EventSink:
    """A publisher bound to one operation's delivery scope.

    Observer failures must not change the operation's result. Cancellation still
    propagates to the owner. The callback is injected, never global or persisted.
    """

    publish: Callable[[AgentEvent], Awaitable[None]] | None = None

    async def emit(self, event: AgentEvent) -> None:
        if self.publish is None:
            return
        try:
            await self.publish(event)
        except Exception:
            logger.exception("Failed to publish {}", type(event).__name__)


NO_EVENTS = EventSink()
