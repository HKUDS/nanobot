"""Async message queue for decoupled channel-agent communication."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.bus.events import DashboardEvent, InboundMessage, OutboundMessage

# Type alias for observer callbacks
Observer = Callable[[Any], Coroutine[Any, Any, None]]


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.

    Observers can subscribe to inbound/outbound messages and dashboard events
    without consuming them (non-interfering monitoring).
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._inbound_observers: list[Observer] = []
        self._outbound_observers: list[Observer] = []
        self._dashboard_observers: list[Observer] = []

    # ------------------------------------------------------------------
    # Inbound (channel → agent)
    # ------------------------------------------------------------------

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)
        await self._notify(self._inbound_observers, msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    # ------------------------------------------------------------------
    # Outbound (agent → channel)
    # ------------------------------------------------------------------

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)
        await self._notify(self._outbound_observers, msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    # ------------------------------------------------------------------
    # Dashboard events (agent internals → dashboard)
    # ------------------------------------------------------------------

    async def emit_dashboard_event(self, event: DashboardEvent) -> None:
        """Emit a dashboard event to all subscribed observers."""
        await self._notify(self._dashboard_observers, event)

    # ------------------------------------------------------------------
    # Observer management
    # ------------------------------------------------------------------

    def add_inbound_observer(self, cb: Observer) -> None:
        self._inbound_observers.append(cb)

    def add_outbound_observer(self, cb: Observer) -> None:
        self._outbound_observers.append(cb)

    def add_dashboard_observer(self, cb: Observer) -> None:
        self._dashboard_observers.append(cb)

    def remove_inbound_observer(self, cb: Observer) -> None:
        self._inbound_observers = [o for o in self._inbound_observers if o is not cb]

    def remove_outbound_observer(self, cb: Observer) -> None:
        self._outbound_observers = [o for o in self._outbound_observers if o is not cb]

    def remove_dashboard_observer(self, cb: Observer) -> None:
        self._dashboard_observers = [o for o in self._dashboard_observers if o is not cb]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    async def _notify(observers: list[Observer], payload: Any) -> None:
        for ob in observers:
            try:
                await ob(payload)
            except Exception as e:
                logger.debug("Observer notification failed: {}", e)
