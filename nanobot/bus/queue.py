"""Queued delivery of messages and typed events between core and channels."""

import asyncio
from collections.abc import Mapping
from typing import Any

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import outbound_message_for_event
from nanobot.events import AgentEvent


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue. Core operations publish text,
    media, or typed events to the same routed outbound queue, independently of
    whether an LLM produced them. Channel adapters own their wire projection.
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Queue a routed message or event for its channel."""
        await self.outbound.put(msg)

    async def publish_event(
        self,
        event: AgentEvent,
        *,
        channel: str,
        chat_id: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue a typed event using the existing outbound delivery contract.

        The bus transports event values without inspecting their fields. Known
        events retain their text fallback; channel adapters decide how to render
        or ignore events they receive.
        """
        await self.publish_outbound(outbound_message_for_event(
            channel=channel, chat_id=chat_id, event=event, metadata=metadata,
        ))

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
