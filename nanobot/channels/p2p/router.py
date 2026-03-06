"""Message router for P2P channel."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger


@dataclass
class P2PMessage:
    """P2P message structure."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender_id: str = ""
    receiver_id: str | None = None
    content: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    message_type: str = "direct"  # "direct", "broadcast", "peer_exchange"
    metadata: dict[str, Any] = field(default_factory=dict)


class MessageRouter:
    """Routes messages between peers."""

    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self._message_queue: asyncio.Queue[P2PMessage] = asyncio.Queue(maxsize=100)
        self._seen_messages: set[str] = set()
        self._max_seen = 1000  # Limit memory for seen messages

    def route_message(self, message: P2PMessage) -> str | None:
        """
        Determine the target peer for a message.

        Returns the target peer ID or None for broadcast.
        """
        # If it's a direct message addressed to us
        if message.receiver_id == self.peer_id:
            return message.sender_id  # Reply to sender

        # If it's a broadcast, reply to sender
        if message.message_type == "broadcast":
            return message.sender_id

        # Otherwise, it's a direct message to someone else - forward it
        return message.receiver_id

    def is_duplicate(self, message_id: str) -> bool:
        """Check if we've seen this message before."""
        if message_id in self._seen_messages:
            return True

        # Add to seen messages
        self._seen_messages.add(message_id)

        # Trim if too many
        if len(self._seen_messages) > self._max_seen:
            # Remove oldest half
            seen_list = list(self._seen_messages)
            self._seen_messages = set(seen_list[len(seen_list)//2:])

        return False

    async def enqueue_message(self, message: P2PMessage) -> bool:
        """
        Add message to queue.

        Returns True if queued, False if queue full.
        """
        try:
            self._message_queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            logger.warning("Message queue full, dropping message")
            return False

    async def dequeue_message(self, timeout: float = 1.0) -> P2PMessage | None:
        """Get next message from queue."""
        try:
            return await asyncio.wait_for(
                self._message_queue.get(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return None

    @property
    def queue_size(self) -> int:
        """Current queue size."""
        return self._message_queue.qsize()

    @property
    def is_full(self) -> bool:
        """Check if queue is full."""
        return self._message_queue.full()
