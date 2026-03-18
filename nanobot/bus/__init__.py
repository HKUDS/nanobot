"""Message bus module for decoupled channel-agent communication."""

from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus

__all__ = ["CanonicalEventBuilder", "MessageBus", "InboundMessage", "OutboundMessage"]
