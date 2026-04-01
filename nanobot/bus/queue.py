"""Async message queue for decoupled channel-agent communication."""

import asyncio
from collections.abc import Callable
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage, SystemEvent


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._system_subscribers: list[Callable[[SystemEvent], Any]] = []

    def subscribe_system(self, callback: Callable[[SystemEvent], Any]) -> None:
        """Subscribe to system events."""
        self._system_subscribers.append(callback)

    async def publish_system(self, event: SystemEvent) -> None:
        """Publish a system event to all subscribers."""
        for callback in self._system_subscribers:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning("系统事件订阅者失败: {}", e)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
