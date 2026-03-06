"""Message bus backend implementations."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from nanobot.bus.events import InboundMessage, OutboundMessage


class BusBackend(ABC):
    """Abstract backend for inbound/outbound message transport."""

    @abstractmethod
    async def publish_inbound(self, msg: InboundMessage) -> None:
        pass

    @abstractmethod
    async def consume_inbound(self) -> InboundMessage:
        pass

    @abstractmethod
    async def publish_outbound(self, msg: OutboundMessage) -> None:
        pass

    @abstractmethod
    async def consume_outbound(self) -> OutboundMessage:
        pass

    @property
    @abstractmethod
    def inbound_size(self) -> int:
        pass

    @property
    @abstractmethod
    def outbound_size(self) -> int:
        pass


class InMemoryBusBackend(BusBackend):
    """Default in-process asyncio queue backend."""

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        return self.outbound.qsize()
