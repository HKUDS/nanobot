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
class RetryStatusEvent(AgentEvent):
    """Sanitized retry lifecycle for one model request chain."""

    state: Literal["waiting", "recovered", "cleared", "exhausted"]
    attempt: int
    max_attempts: int | None
    error_kind: str
    next_retry_at: float | None = None


@dataclass(frozen=True)
class RecoveryStateEvent(AgentEvent):
    status: str
    recovery_id: str
    reason: str | None = None
    attempts: int = 0
    can_continue: bool | None = None


@dataclass(frozen=True)
class EventSink:
    """A thin send callback bound to one operation's MessageBus route.

    Operations use best-effort emit; execution hooks await publish directly so
    output failures retain their runner error semantics. Both propagate
    cancellation. This owns no queue or subscribers. accepts lets expensive
    producers skip work when the bound consumer cannot use their event type.
    """

    publish: Callable[[AgentEvent], Awaitable[None]] | None = None
    accepts_type: Callable[[type[AgentEvent]], bool] | None = None

    def accepts(self, event_type: type[AgentEvent]) -> bool:
        """Whether producing this event has a consumer in the bound scope."""
        return self.publish is not None and (
            self.accepts_type is None or self.accepts_type(event_type)
        )

    async def emit(self, event: AgentEvent) -> None:
        if self.publish is None:
            return
        try:
            await self.publish(event)
        except Exception:
            logger.exception("Failed to publish {}", type(event).__name__)


NO_EVENTS = EventSink()
