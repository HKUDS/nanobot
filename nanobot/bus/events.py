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
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReactionEvent:
    """Emoji reaction received on a message.

    Channels that support reactions (Telegram, Discord, Slack, Feishu) can
    emit this event so the agent loop can translate it into feedback.
    """

    channel: str
    sender_id: str
    chat_id: str
    emoji: str  # e.g. "\U0001f44d", "THUMBSUP", "+1"
    message_id: str | None = None  # platform message ID the reaction is on
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ----- convenience helpers -----

    _POSITIVE_EMOJIS: frozenset[str] = frozenset(
        {
            "\U0001f44d",
            "+1",
            "thumbsup",
            "THUMBSUP",
            "\u2764",
            "heart",
            "HEART",
            "\U0001f389",
            "tada",
            "\U0001f44f",
            "clap",
            "\U0001f60d",
            "star",
            "\u2b50",
            "ok",
            "OK",
            "DONE",
            "\u2705",
            "check",
            "white_check_mark",
        }
    )
    _NEGATIVE_EMOJIS: frozenset[str] = frozenset(
        {
            "\U0001f44e",
            "-1",
            "thumbsdown",
            "THUMBSDOWN",
            "\U0001f612",
            "\U0001f620",
            "angry",
            "confused",
            "\U0001f615",
            "\U0001f641",
            "disappointed",
        }
    )

    @property
    def rating(self) -> str | None:
        """Map emoji to 'positive' / 'negative' or None if ambiguous."""
        e = self.emoji.strip().lower()
        if e in self._POSITIVE_EMOJIS or self.emoji in self._POSITIVE_EMOJIS:
            return "positive"
        if e in self._NEGATIVE_EMOJIS or self.emoji in self._NEGATIVE_EMOJIS:
            return "negative"
        return None
