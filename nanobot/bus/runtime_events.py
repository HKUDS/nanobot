"""Runtime event bus for agent state notifications.

This bus is separate from :mod:`nanobot.bus.queue`: message bus events are
user/chat delivery, while runtime events are in-process state notifications
that optional subscribers such as WebUI adapters may render.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass(frozen=True)
class RuntimeEventContext:
    """Routing context common to turn-scoped runtime events."""

    channel: str
    chat_id: str
    session_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionTurnStarted:
    """A user/system turn has loaded its session and is about to build context."""

    context: RuntimeEventContext


@dataclass(frozen=True)
class TurnRunStatusChanged:
    """Visible run status changed for a turn."""

    context: RuntimeEventContext
    status: str
    started_at: float | None = None


@dataclass(frozen=True)
class TurnCompleted:
    """A turn has delivered its final user-visible response."""

    context: RuntimeEventContext
    latency_ms: int | None = None
    runtime: Any | None = None


@dataclass(frozen=True)
class GoalStateChanged:
    """A session's sustained-goal state changed."""

    context: RuntimeEventContext
    session_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeModelChanged:
    """The active runtime model/preset changed."""

    model: str
    model_preset: str | None


RuntimeEvent = (
    SessionTurnStarted
    | TurnRunStatusChanged
    | TurnCompleted
    | GoalStateChanged
    | RuntimeModelChanged
)
RuntimeEventType = (
    type[SessionTurnStarted]
    | type[TurnRunStatusChanged]
    | type[TurnCompleted]
    | type[GoalStateChanged]
    | type[RuntimeModelChanged]
)
RuntimeEventHandler = Callable[[Any], Awaitable[None] | None]
_HandlerEntry = tuple[RuntimeEventType | None, RuntimeEventHandler]


class RuntimeEventBus:
    """Small in-process pub/sub bus for runtime state.

    Subscribers run in registration order. ``publish`` awaits async handlers so
    callers can preserve ordering when a runtime event must follow a user
    message. ``publish_nowait`` is available for synchronous call sites.
    """

    def __init__(self) -> None:
        self._handlers: list[_HandlerEntry] = []

    def subscribe(
        self,
        handler: RuntimeEventHandler,
        event_type: RuntimeEventType | None = None,
    ) -> Callable[[], None]:
        entry = (event_type, handler)
        self._handlers.append(entry)

        def _unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._handlers.remove(entry)

        return _unsubscribe

    async def publish(self, event: RuntimeEvent) -> None:
        for event_type, handler in list(self._handlers):
            if event_type is not None and not isinstance(event, event_type):
                continue
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("runtime event handler failed for {}", type(event).__name__)

    def publish_nowait(self, event: RuntimeEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("dropping runtime event without a running loop: {}", type(event).__name__)
            return
        loop.create_task(self.publish(event))
