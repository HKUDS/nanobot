"""Message bus module for decoupled channel-agent communication."""

from blackcat.bus.events import InboundMessage, OutboundMessage
from blackcat.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
