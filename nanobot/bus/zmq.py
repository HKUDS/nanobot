"""ZeroMQ message bus for cross-instance agent communication."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .config import BusConfig
from .events import InboundMessage, OutboundMessage
from .queue import MessageBus

logger = logging.getLogger(__name__)

# Field keys (mirror redis.py for wire compatibility — optional)
_FIELD_SESSION_KEY = "session_key"
_FIELD_CONTENT = "content"
_FIELD_SENDER = "sender"
_FIELD_METADATA = "metadata"
_FIELD_CHANNEL = "channel"
_FIELD_CHAT_ID = "chat_id"
_FIELD_SENDER_ID = "sender_id"

# Separator between topic and payload in ZMQ multipart messages
# Frame 1: recipient topic (agent_id)
# Frame 2: JSON-encoded message fields


class ZMQMessageBus(MessageBus):
    """Message bus using ZeroMQ PUB/SUB sockets.

    Each agent binds a PUB socket on its own port and connects SUB
    sockets to all peer PUB ports.  Messages are topic-routed by
    recipient agent_id so every agent only receives messages addressed
    to it.
    """

    def __init__(self, config: BusConfig) -> None:
        super().__init__(agent_id=config.agent_id)
        self._config = config

        # Port we bind our PUB socket on
        self._port: int = getattr(config, "port", 5550)

        # Peers: {agent_id: "tcp://host:port"}
        self._peers: dict[str, str] = getattr(config, "peers", {})

        # ZMQ state — created in start()
        self._ctx: Any = None
        self._pub: Any = None      # PUB socket for sending
        self._subs: list[Any] = []  # SUB sockets for receiving
        self._poller_task: asyncio.Task | None = None
        self._running = False

        # Local queues (shared with base class)
        # self.inbound     — asyncio.Queue from MessageBus
        # self.outbound    — asyncio.Queue from MessageBus
        # self.agent_inbound — asyncio.Queue from MessageBus

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        from zmq import asyncio as zma

        self._ctx = zma.Context()

        # -- PUB socket: bind on our port --------------------------------
        pub: Any = self._ctx.socket(zma.PUB)
        addr = f"tcp://*:{self._port}"
        pub.bind(addr)
        self._pub = pub
        logger.info("ZMQ PUB bound to %s", addr)

        # -- SUB sockets: connect to each peer ---------------------------
        for peer_id, peer_addr in self._peers.items():
            sub: Any = self._ctx.socket(zma.SUB)
            # Subscribe to our own agent_id so we only get messages
            # addressed to us (or broadcast with "*").
            sub.subscribe(self.agent_id.encode("utf-8"))
            sub.subscribe(b"*")  # allow broadcast
            sub.connect(peer_addr)
            self._subs.append(sub)
            logger.info("ZMQ SUB connected to %s (%s)", peer_id, peer_addr)

        # Give ZMQ a moment to establish connections before publishing
        await asyncio.sleep(0.1)

        # -- Background poller -------------------------------------------
        self._poller_task = asyncio.create_task(self._poller_loop())

    async def stop(self) -> None:
        self._running = False

        if self._poller_task is not None:
            self._poller_task.cancel()
            try:
                await self._poller_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poller_task = None

        for sub in self._subs:
            sub.close()
        self._subs.clear()

        if self._pub is not None:
            self._pub.close()
            self._pub = None

        if self._ctx is not None:
            self._ctx.term()
            self._ctx = None

        logger.info("ZMQ bus stopped")

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish_agent_message(self, msg: InboundMessage) -> None:
        """Publish an agent message to the target agent via ZMQ."""
        if not self._running or self._pub is None:
            return

        target_agent = (msg.metadata or {}).get("target_agent")
        if not target_agent:
            logger.debug("publish_agent_message: no target_agent, skipping")
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

        # ZMQ multipart: [recipient_topic, payload]
        topic = target_agent.encode("utf-8")
        await self._pub.send_multipart([topic, payload])

        logger.debug(
            "ZMQ published agent message -> %s (content=%.60s)",
            target_agent, msg.content,
        )

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Route inbound CLI message — local + cross-instance if target_agent set."""
        target = (msg.metadata or {}).get("target_agent")
        is_for_me = target is None or target == self._agent_id or target == "*"

        if is_for_me:
            await self.inbound.put(msg)

        if target is not None and target != self._agent_id:
            # Cross-instance: publish via ZMQ
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
    # Poller
    # ------------------------------------------------------------------

    async def _poller_loop(self) -> None:
        """Background task: read messages from all SUB sockets."""
        from zmq import asyncio as zma

        if not self._subs:
            logger.warning("ZMQ poller: no peers to listen on")
            return

        poller = zma.Poller()
        for sub in self._subs:
            poller.register(sub, zma.POLLIN)

        while self._running:
            try:
                events = await poller.poll(timeout=1000)  # 1s timeout
                for sock, event in events:
                    if event != zma.POLLIN:
                        continue
                    frames = await sock.recv_multipart()
                    if len(frames) < 2:
                        logger.debug("ZMQ: short frame %d", len(frames))
                        continue

                    topic = frames[0].decode("utf-8")
                    payload = frames[1].decode("utf-8")

                    # Parse fields
                    try:
                        fields: dict[str, Any] = json.loads(payload)
                    except json.JSONDecodeError:
                        logger.warning("ZMQ: invalid JSON payload from topic=%s", topic)
                        continue

                    msg = self._fields_to_agent_message(fields)
                    if msg is not None:
                        await self.agent_inbound.put(msg)
                        logger.debug(
                            "ZMQ received agent message from %s (len=%d)",
                            msg.sender, len(msg.content or ""),
                        )

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("ZMQ poller error")
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Deserialization
    # ------------------------------------------------------------------

    @staticmethod
    def _fields_to_agent_message(fields: dict[str, Any]) -> InboundMessage | None:
        """Reconstruct an InboundMessage from JSON-serialised fields.

        Returns None if the message is not an agent message (no target_agent).
        """
        metadata_raw = fields.get(_FIELD_METADATA, "{}")
        if isinstance(metadata_raw, str):
            try:
                metadata = json.loads(metadata_raw)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        else:
            metadata = metadata_raw or {}

        # Only put into agent_inbound if target_agent is set
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