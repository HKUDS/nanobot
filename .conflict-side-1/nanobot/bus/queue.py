"""Async message queue for decoupled channel-agent communication."""

import asyncio
import logging

from nanobot.bus.events import InboundMessage, OutboundMessage

logger = logging.getLogger(__name__)


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self, agent_id: str = ""):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.agent_inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._agent_id = agent_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start any background bus tasks.

        The in-process bus has no background tasks so this is a no-op.
        Subclasses like :class:`RedisMessageBus` override this to start
        a background Redis poller.
        """

    async def stop(self) -> None:
        """Stop any background bus tasks.

        The in-process bus has no background tasks so this is a no-op.
        Subclasses like :class:`RedisMessageBus` override this to cancel
        their background poller.
        """

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent.

        If ``metadata.target_agent`` is set and doesn't match *our*
        ``agent_id``, the message is silently dropped so that only the
        intended agent receives it.
        """
        target = (msg.metadata or {}).get("target_agent")
        if target is not None and target != self._agent_id and target != "*":
            logger.debug(
                "Dropping inbound message for %s (we are %s)",
                target, self._agent_id,
            )
            return
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    # ------------------------------------------------------------------
    # Agent-to-agent messaging
    # ------------------------------------------------------------------

    async def publish_agent_message(self, msg: InboundMessage) -> None:
        """Publish a message destined for another agent.

        In the in-process bus this is a no-op (no cross-instance delivery).
        Subclasses like :class:`RedisMessageBus` override this to write
        directly to the Redis stream so the remote agent's poller picks it up.
        """
        logger.debug(
            "publish_agent_message: in-process bus cannot route to other agents. "
            "Use RedisMessageBus for cross-instance delivery."
        )

    async def consume_agent_message(self) -> InboundMessage:
        """Consume the next agent-to-agent message (blocks until available)."""
        return await self.agent_inbound.get()

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()

    @property
    def agent_id(self) -> str:
        """The agent identity this bus is configured for.

        Returns the agentId from config (e.g. ``"bot-personal"``). Subclasses
        like :class:`RedisMessageBus` set this from the config; the in-process
        bus defaults to an empty string.
        """
        return getattr(self, "_agent_id", "")
