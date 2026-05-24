"""NATS message bus for cross-instance agent communication."""

from __future__ import annotations

import json
import logging
from typing import Any

from .events import InboundMessage, OutboundMessage
from .queue import MessageBus

logger = logging.getLogger(__name__)

# Field keys (same across all bus backends)
_FIELD_SESSION_KEY = "session_key"
_FIELD_CONTENT = "content"
_FIELD_SENDER = "sender"
_FIELD_METADATA = "metadata"
_FIELD_CHANNEL = "channel"
_FIELD_CHAT_ID = "chat_id"
_FIELD_SENDER_ID = "sender_id"


class NATSMessageBus(MessageBus):
    """Message bus using NATS publish/subscribe.

    Each agent connects to the NATS server and subscribes to its own
    subject::

        {subject_prefix}.{own_agent_id}

    Messages are published on the recipient's subject::

        {subject_prefix}.{target_agent_id}

    Broadcast (target_agent = ``"*"``) uses the ``broadcast`` subject::

        {subject_prefix}.broadcast

    NATS handles reconnection automatically — subscriptions are
    re-established after a reconnect.
    """

    def __init__(self, config: Any) -> None:
        super().__init__(agent_id=getattr(config, "agent_id", ""))
        self._config = config

        # Connection settings
        self._url: str = getattr(config, "url", "nats://localhost:4222")
        self._subject_prefix: str = getattr(config, "subject_prefix", "nanobot.agent")

        # NATS client state — set in start()
        self._nc: Any = None
        self._sub: Any = None       # Our own subscription
        self._running = False

        # Local queues (inherited from MessageBus)
        # self.inbound       — CLI input (asyncio.Queue)
        # self.outbound      — CLI output (asyncio.Queue)
        # self.agent_inbound — cross-instance messages (asyncio.Queue)

    # ------------------------------------------------------------------
    # Properties / helpers
    # ------------------------------------------------------------------

    def _subject_for_agent(self, agent_id: str) -> str:
        """Return the NATS subject for a given agent_id."""
        return f"{self._subject_prefix}.{agent_id}"

    @property
    def _my_subject(self) -> str:
        return self._subject_for_agent(self._agent_id)

    @property
    def _broadcast_subject(self) -> str:
        return f"{self._subject_prefix}.broadcast"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        import nats

        # Connect to NATS server
        try:
            self._nc = await nats.connect(
                self._url,
                name=f"nanobot-{self._agent_id}",
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,  # infinite
                # Log-level for noisy reconnect logging
                # error_handler=self._on_nats_error,
            )
        except Exception:
            logger.exception("NATS connect failed to %s", self._url)
            self._running = False
            raise

        # Subscribe to our own subject
        self._sub = await self._nc.subscribe(
            self._my_subject,
            cb=self._on_message,
        )
        logger.info(
            "NATS connected to %s, subscribed to %s",
            self._url, self._my_subject,
        )

    async def stop(self) -> None:
        self._running = False

        # Unsubscribe
        if self._sub is not None:
            try:
                await self._sub.unsubscribe()
            except Exception:
                pass
            self._sub = None

        # Drain and close NATS connection
        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:
                pass
            try:
                await self._nc.close()
            except Exception:
                pass
            self._nc = None

        logger.info("NATS bus stopped")

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish_agent_message(self, msg: InboundMessage) -> None:
        """Publish an agent-to-agent message via NATS."""
        if not self._running or self._nc is None:
            logger.debug("NATS publish_agent_message: bus not running")
            return

        target_agent = (msg.metadata or {}).get("target_agent")
        if not target_agent:
            return

        # Serialize message fields as JSON
        fields = {
            _FIELD_SESSION_KEY: msg.session_key,
            _FIELD_CONTENT: msg.content or "",
            _FIELD_SENDER: msg.sender or "",
            _FIELD_CHANNEL: msg.channel or "bus",
            _FIELD_CHAT_ID: msg.chat_id or "",
            _FIELD_SENDER_ID: msg.sender_id or "",
            _FIELD_METADATA: json.dumps(msg.metadata or {}),
        }
        payload = json.dumps(fields).encode("utf-8")

        # Determine subject: broadcast or specific agent
        if target_agent == "*":
            subject = self._broadcast_subject
        else:
            subject = self._subject_for_agent(target_agent)

        await self._nc.publish(subject, payload)

        logger.debug(
            "NATS published on %s -> %s (content=%.60s)",
            subject, target_agent, msg.content,
        )

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Route inbound CLI message — local + cross-instance if target_agent set."""
        target = (msg.metadata or {}).get("target_agent")
        is_for_me = target is None or target == self._agent_id or target == "*"

        if is_for_me:
            await self.inbound.put(msg)

        if target is not None and target != self._agent_id:
            # Cross-instance: publish via NATS
            await self.publish_agent_message(msg)

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Route outbound response — local only."""
        await self.outbound.put(msg)

    # ------------------------------------------------------------------
    # Consumption
    # ------------------------------------------------------------------

    async def consume_inbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def consume_agent_message(self) -> InboundMessage:
        return await self.agent_inbound.get()

    async def consume_outbound(self) -> OutboundMessage:
        return await self.outbound.get()

    # ------------------------------------------------------------------
    # NATS callback
    # ------------------------------------------------------------------

    async def _on_message(self, msg: Any) -> None:
        """NATS subscription callback — deserialise and enqueue."""
        try:
            fields: dict[str, Any] = json.loads(msg.data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("NATS: invalid message payload: %s", exc)
            return

        inbound = self._fields_to_agent_message(fields)
        if inbound is None:
            logger.debug("NATS: received message without target_agent, dropping")
            return

        await self.agent_inbound.put(inbound)
        logger.debug(
            "NATS received agent message from %s (len=%d)",
            inbound.sender, len(inbound.content or ""),
        )

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _fields_to_agent_message(fields: dict[str, Any]) -> InboundMessage | None:
        """Reconstruct an InboundMessage from JSON-serialised fields.

        Returns None if the message has no target_agent (shouldn't happen
        with NATS since each agent subscribes to its own subject, but
        guards against misconfigured publishers).
        """
        metadata_raw = fields.get(_FIELD_METADATA, "{}")
        if isinstance(metadata_raw, str):
            try:
                metadata = json.loads(metadata_raw)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        else:
            metadata = metadata_raw or {}

        # Guard: only accept messages with target_agent
        target = metadata.get("target_agent")
        if not target:
            return None

        return InboundMessage(
            channel=fields.get(_FIELD_CHANNEL, "bus"),
            sender_id=fields.get(_FIELD_SENDER_ID, ""),
            chat_id=fields.get(_FIELD_CHAT_ID, ""),
            content=fields.get(_FIELD_CONTENT, ""),
            sender=fields.get(_FIELD_SENDER, ""),
            session_key_override=fields.get(_FIELD_SESSION_KEY) or None,
            metadata=metadata,
        )