"""Async message queue for decoupled channel-agent communication."""

from nanobot.bus.backends import BusBackend, InMemoryBusBackend
from nanobot.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self, backend: BusBackend | None = None):
        self.backend: BusBackend = backend or InMemoryBusBackend()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.backend.publish_inbound(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.backend.consume_inbound()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.backend.publish_outbound(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.backend.consume_outbound()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.backend.inbound_size

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.backend.outbound_size
