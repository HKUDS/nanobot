"""Transport interfaces for external adapter integration."""

from nanobot.transport.contracts import (
    AttachmentRef,
    InboundTransportMessage,
    OutboundTransportEvent,
    OutboundTransportMessage,
)

__all__ = [
    "AttachmentRef",
    "InboundTransportMessage",
    "OutboundTransportMessage",
    "OutboundTransportEvent",
]
