"""Event types for the message bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


@dataclass
class StreamChunk:
    """A streaming chunk from the agent."""

    content: str  # Content of this chunk
    is_final: bool = False  # Whether this is the last chunk
    finish_reason: str | None = None  # stop, tool_calls, length, error, etc.


# Type alias for stream callback
StreamCallback = "Callable[[StreamChunk], Awaitable[None]]"


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str  # telegram, discord, slack, whatsapp, openapi
    sender_id: str  # User identifier
    chat_id: str  # Chat/channel identifier
    content: str  # Message text
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # Media URLs
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific data
    stream_callback: StreamCallback | None = None  # Optional callback for streaming

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
        return f"{self.channel}:{self.chat_id}"

    @property
    def wants_stream(self) -> bool:
        """Check if this message requests streaming response."""
        return self.stream_callback is not None


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
