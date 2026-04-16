"""Async message queue for decoupled channel-agent communication."""

import asyncio
import os

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage

_DEFAULT_INBOUND_MAXSIZE = 100


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.

    The inbound queue is bounded (default 100, override via
    ``NANOBOT_BUS_INBOUND_MAXSIZE``) to prevent unbounded memory growth
    when the agent falls behind.  The outbound queue stays unbounded so
    agent responses are never silently lost.
    """

    def __init__(self):
        maxsize = int(os.environ.get("NANOBOT_BUS_INBOUND_MAXSIZE", _DEFAULT_INBOUND_MAXSIZE))
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> bool:
        """Publish a message from a channel to the agent.

        Returns ``True`` if the message was enqueued, ``False`` if the
        inbound queue is full and the message was dropped.
        """
        try:
            self.inbound.put_nowait(msg)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "Inbound queue full ({} msgs) — dropped message from {}:{}",
                self.inbound.qsize(),
                msg.channel,
                msg.chat_id,
            )
            return False

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
