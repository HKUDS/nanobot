"""Message bus module for decoupled channel-agent communication."""

from janniebot.bus.events import InboundMessage, OutboundMessage
from janniebot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
