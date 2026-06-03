"""Event types for the message bus."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Optional ``OutboundMessage.metadata`` key for structured, channel-agnostic UI
# payloads. Value is JSON-serializable with at least ``kind``; rich clients may
# render it and other channels may ignore unknown keys.
OUTBOUND_META_AGENT_UI = "_agent_ui"

# Internal-only inbound metadata used by in-process channels to ask the agent
# loop to update runtime state without going through a user session.
INBOUND_META_RUNTIME_CONTROL = "_runtime_control"
RUNTIME_CONTROL_ACK = "_ack"
RUNTIME_CONTROL_MCP_RELOAD = "mcp_reload"
RUNTIME_CONTROL_MCP_TOOLS_CHANGED = "mcp_tools_changed"

# Metadata key carrying the server name that sent the tools/list_changed notification.
RUNTIME_CONTROL_MCP_SERVER_NAME = "_mcp_server_name"


@dataclass
class InboundMessage:
    """Message received from a chat channel (or system runtime control)."""

    channel: str  # telegram, discord, slack, whatsapp, system
    sender_id: str  # User identifier or system source
    chat_id: str  # Chat/channel identifier, or "runtime" for control messages
    content: str  # Message text or runtime control signal
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
    """Message to send to a chat channel.

    ``metadata`` can carry routing (``message_id``, …), trace flags (``_progress``),
    and optional ``OUTBOUND_META_AGENT_UI`` blobs for rich clients; non-WebUI
    channels may ignore unknown keys.
    """

    channel: str
    chat_id: str
    content: str
    reply_to: str | None = None
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    buttons: list[list[str]] = field(default_factory=list)
