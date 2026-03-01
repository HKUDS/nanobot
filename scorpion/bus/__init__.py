"""Message bus module for decoupled channel-agent communication."""

from scorpion.bus.events import InboundMessage, OutboundMessage
from scorpion.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
