"""Message bus module for decoupled channel-agent communication."""

from nanobot.bus.backends import BusBackend, InMemoryBusBackend
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus

__all__ = [
    "BusBackend",
    "InMemoryBusBackend",
    "MessageBus",
    "InboundMessage",
    "OutboundMessage",
]
