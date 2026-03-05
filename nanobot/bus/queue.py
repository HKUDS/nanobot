"""Async message queue for decoupled channel-agent communication."""

import asyncio

from nanobot.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._event_channels: dict[str, asyncio.Queue[dict]] = {}

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

    async def publish_event(self, session_key: str, content: str) -> None:
        """Publish an event to a specific session's event channel."""
        if session_key not in self._event_channels:
            self._event_channels[session_key] = asyncio.Queue()
        await self._event_channels[session_key].put(content)

    async def check_events(self, session_key: str) -> str | None:
        """Non-blocking check for accumulated events. Returns formatted string or None."""
        queue = self._event_channels.get(session_key)
        if not queue:
            return None

        # Drain all available events without blocking
        events = []
        while not queue.empty():
            try:
                events.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        # Clean up empty queues to prevent memory leak
        if queue.empty():
            self._event_channels.pop(session_key, None)

        return "\n".join(f"- {e}" for e in events) if events else None
