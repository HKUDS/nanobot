"""Event types for the message bus."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class InboundAttachment:
    """Structured inbound attachment metadata for prompt context.

    Contract:
    - ``content`` remains the user's plain authored text or lightweight attachment markers.
    - Attachment-derived context travels separately via ``InboundMessage.attachments``.
    - ``extracted_text`` is best-effort, already truncated for prompt safety, and must be
      interpreted as attachment context rather than user-authored chat text.
    """

    kind: str
    name: str | None = None
    local_path: str | None = None
    source: str | None = None
    mime_type: str | None = None
    extracted_text: str | None = None
    extracted_text_source: str | None = None
    extracted_text_truncated: bool = False
    extraction_note: str | None = None

    def to_prompt_dict(self) -> dict[str, Any]:
        """Return a compact JSON-serializable attachment payload for prompt context."""
        return {k: v for k, v in asdict(self).items() if v not in (None, "", [], {}) and v is not False}


@dataclass
class InboundMessage:
    """Message received from a chat channel."""

    channel: str  # telegram, discord, slack, whatsapp
    sender_id: str  # User identifier
    chat_id: str  # Chat/channel identifier
    content: str  # Message text
    timestamp: datetime = field(default_factory=datetime.now)
    media: list[str] = field(default_factory=list)  # Media URLs
    attachments: list[InboundAttachment] = field(default_factory=list)  # Structured attachment context
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

