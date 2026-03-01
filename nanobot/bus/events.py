"""Event types for the message bus."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str  # telegram, discord, slack, whatsapp
    sender_id: str  # User identifier
    chat_id: str  # Chat/channel identifier
    content: str  # Message text
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # Media URLs
    metadata: dict[str, Any] = field(default_factory=dict)  # Channel-specific data
    session_key_override: str | None = None  # Optional override for thread-scoped sessions

    @property
    def session_key(self) -> str:
        """Unique key for session identification."""
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass
class OutboundMessage:
    """Message to send to a chat channel."""

    channel: str
    chat_id: str
    content: str
    request_id: str | None = None  # Optional correlation ID for delivery acknowledgement
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    sticker_id: str | None = None
    reaction: str | None = None  # emoji reaction, e.g. "👍"
    reaction_message_id: int | None = None  # target Telegram message_id for reaction
    silent: bool = False  # If True, channel should only stop typing indicator, not send anything
    metadata: dict[str, Any] = field(default_factory=dict)
