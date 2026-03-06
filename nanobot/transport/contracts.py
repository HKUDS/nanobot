"""Transport-level message contracts for external adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from nanobot.bus.events import InboundMessage, OutboundMessage


class AttachmentRef(BaseModel):
    """Attachment reference used by external adapters."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None  # Optional adapter-side identifier for dedup/tracing.
    type: Literal["image", "audio", "video", "file"] | None = None  # High-level attachment kind.
    mime_type: str | None = None  # Specific media type, e.g. "image/png", "audio/mpeg".
    url: str | None = None  # Remote source (HTTP/S, object storage, CDN).
    local_path: str | None = None  # Local source path (same host/container as gateway).
    size_bytes: int | None = None
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InboundTransportMessage(BaseModel):
    """Inbound payload accepted from external adapters."""

    model_config = ConfigDict(extra="ignore")

    message_id: str | None = None
    session_key: str | None = None
    channel: str
    chat_id: str
    sender_id: str
    content: str = ""
    media: list[str] = Field(default_factory=list)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def _collect_media_refs(self) -> list[str]:
        refs = list(self.media)
        for att in self.attachments:
            # Prefer local_path over url when both are provided.
            if att.local_path:
                refs.append(att.local_path)
            elif att.url:
                refs.append(att.url)
        # preserve order while deduplicating
        return list(dict.fromkeys(refs))

    def to_bus_message(self) -> InboundMessage:
        metadata = dict(self.metadata)
        if self.message_id:
            metadata.setdefault("message_id", self.message_id)
        if self.attachments:
            metadata["attachments"] = [a.model_dump(mode="json") for a in self.attachments]
        return InboundMessage(
            channel=self.channel,
            sender_id=self.sender_id,
            chat_id=self.chat_id,
            content=self.content,
            media=self._collect_media_refs(),
            metadata=metadata,
            session_key_override=self.session_key,
        )


class OutboundTransportMessage(BaseModel):
    """Outbound payload emitted to external adapters."""

    model_config = ConfigDict(extra="ignore")

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_bus_message(cls, msg: OutboundMessage) -> "OutboundTransportMessage":
        return cls(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=msg.content,
            reply_to=msg.reply_to,
            media=list(msg.media or []),
            metadata=dict(msg.metadata or {}),
        )


TransportEventType = Literal[
    "message.started",
    "message.delta",
    "message.completed",
    "message.failed",
    "tool.started",
    "tool.finished",
]


class OutboundTransportEvent(BaseModel):
    """Event envelope for streaming outbound events."""

    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: TransportEventType
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    message: OutboundTransportMessage

    @classmethod
    def from_bus_message(cls, msg: OutboundMessage) -> "OutboundTransportEvent":
        metadata = msg.metadata or {}
        if metadata.get("_progress"):
            event_type: TransportEventType = "message.delta"
        else:
            event_type = "message.completed"
        return cls(
            event_type=event_type,
            message=OutboundTransportMessage.from_bus_message(msg),
        )
