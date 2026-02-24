"""Async message queue for decoupled channel-agent communication."""

import asyncio
from datetime import datetime
from typing import Awaitable, Callable

from loguru import logger

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
        self._outbound_subscribers: dict[str, list[Callable[[OutboundMessage], Awaitable[None]]]] = {}
        self._outbound_waiters: dict[str, asyncio.Future[tuple[bool, str | None]]] = {}
        self._active_inbound_session: str | None = None
        self._inbound_collect_buffer: dict[str, list[InboundMessage]] = {}
        self._inbound_collect_lock = asyncio.Lock()
        self._running = False

    @staticmethod
    def _timestamp_to_text(value: datetime | str) -> str:
        """Normalize timestamp values for metadata serialization."""
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    @classmethod
    def _merge_buffered_messages(cls, messages: list[InboundMessage]) -> InboundMessage:
        """Merge buffered inbound messages into one follow-up message."""
        first = messages[0]
        if len(messages) == 1:
            merged_content = messages[0].content
        else:
            merged_content = "\n\n".join(f"[{msg.sender_id}] {msg.content}" for msg in messages)
        merged_media: list[str] = [item for msg in messages for item in msg.media]

        collected_messages = [
            {
                "sender_id": msg.sender_id,
                "content": msg.content,
                "timestamp": cls._timestamp_to_text(msg.timestamp),
                "media": list(msg.media),
                "metadata": dict(msg.metadata or {}),
            }
            for msg in messages
        ]

        merged_metadata = dict(first.metadata or {})
        merged_metadata["collected_messages"] = collected_messages
        merged_metadata["collected_count"] = len(messages)

        return InboundMessage(
            channel=first.channel,
            sender_id=first.sender_id,
            chat_id=first.chat_id,
            content=merged_content,
            timestamp=first.timestamp,
            media=merged_media,
            metadata=merged_metadata,
        )
    
    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        async with self._inbound_collect_lock:
            if self._active_inbound_session and msg.session_key == self._active_inbound_session:
                buffer = self._inbound_collect_buffer.setdefault(msg.session_key, [])
                buffer.append(msg)
                logger.debug(
                    "Buffered inbound message for {} (buffered={})",
                    msg.session_key,
                    len(buffer),
                )
                return
            self.inbound.put_nowait(msg)
    
    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        msg = await self.inbound.get()
        async with self._inbound_collect_lock:
            self._active_inbound_session = msg.session_key
        return msg

    async def complete_inbound_turn(self, msg: InboundMessage) -> None:
        """Mark an inbound turn as complete and enqueue merged follow-up if buffered."""
        async with self._inbound_collect_lock:
            if self._active_inbound_session != msg.session_key:
                return

            buffered = self._inbound_collect_buffer.pop(msg.session_key, [])
            if buffered:
                merged = self._merge_buffered_messages(buffered)
                self.inbound.put_nowait(merged)
                logger.debug(
                    "Merged {} buffered inbound messages for {}",
                    len(buffered),
                    msg.session_key,
                )

            self._active_inbound_session = None

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    def subscribe_outbound(
        self, 
        channel: str, 
        callback: Callable[[OutboundMessage], Awaitable[None]]
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

    def create_outbound_waiter(self, request_id: str) -> asyncio.Future[tuple[bool, str | None]]:
        """Create a waiter future for outbound delivery acknowledgement."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[tuple[bool, str | None]] = loop.create_future()
        old = self._outbound_waiters.pop(request_id, None)
        if old and not old.done():
            old.set_result((False, "superseded by a newer outbound request"))
        self._outbound_waiters[request_id] = fut
        return fut

    def resolve_outbound_waiter(
        self, request_id: str | None, success: bool, error: str | None = None
    ) -> None:
        """Resolve outbound waiter by request ID."""
        if not request_id:
            return
        fut = self._outbound_waiters.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result((success, error))

    def discard_outbound_waiter(self, request_id: str | None) -> None:
        """Drop outbound waiter without resolving."""
        if not request_id:
            return
        self._outbound_waiters.pop(request_id, None)
    
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
