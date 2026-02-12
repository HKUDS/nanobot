"""Async message queue for decoupled channel-agent communication."""

import asyncio
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage

# Type alias for stream callbacks: async or sync function taking a string chunk
StreamCallback = Callable[[str], Any]


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._outbound_subscribers: dict[
            str, list[Callable[[OutboundMessage], Awaitable[None]]]
        ] = {}
        self._stream_callbacks: dict[str, StreamCallback] = {}
        self._stream_done_events: dict[str, asyncio.Event] = {}
        self._running = False

    def register_stream_callback(self, stream_id: str, callback: StreamCallback) -> None:
        """Register a streaming callback for a message."""
        self._stream_callbacks[stream_id] = callback
        self._stream_done_events[stream_id] = asyncio.Event()

    def get_stream_callback(self, stream_id: str) -> StreamCallback | None:
        """Get and remove a streaming callback (one-time use)."""
        return self._stream_callbacks.pop(stream_id, None)

    def mark_stream_done(self, stream_id: str) -> None:
        """Mark a stream as done (agent loop finished processing)."""
        if stream_id in self._stream_done_events:
            self._stream_done_events[stream_id].set()

    async def wait_stream_done(self, stream_id: str, timeout: float = 300) -> bool:
        """Wait for a stream to complete. Returns True if done, False if timeout."""
        event = self._stream_done_events.get(stream_id)
        if not event:
            return True
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self._stream_done_events.pop(stream_id, None)

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

    def subscribe_outbound(
        self, channel: str, callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """Subscribe to outbound messages for a specific channel."""
        if channel not in self._outbound_subscribers:
            self._outbound_subscribers[channel] = []
        self._outbound_subscribers[channel].append(callback)

    async def dispatch_outbound(self) -> None:
        """
        Dispatch outbound messages to subscribed channels.
        Run this as a background task.
        """
        self._running = True
        while self._running:
            try:
                msg = await asyncio.wait_for(self.outbound.get(), timeout=1.0)
                subscribers = self._outbound_subscribers.get(msg.channel, [])
                for callback in subscribers:
                    try:
                        await callback(msg)
                    except Exception as e:
                        logger.error(f"Error dispatching to {msg.channel}: {e}")
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        """Stop the dispatcher loop."""
        self._running = False

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()
