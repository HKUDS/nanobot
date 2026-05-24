"""Redis pub/sub message bus — NATS-style pub/sub semantics.

Each agent subscribes to its own channel and a broadcast channel::

    {channel_prefix}:{own_agent_id}
    {channel_prefix}:broadcast

Messages are published on the recipient's channel::

    {channel_prefix}:{target_agent_id}

Broadcast (``target_agent = "*"``) publishes to::

    {channel_prefix}:broadcast

The wire format is identical to NATS (same JSON field keys), so a NATS
sender and a Redis receiver are wire-compatible.

Redis pub/sub is **fire-and-forget** — an unsubscribed agent will miss
the message. This mirrors NATS behaviour. For persistent delivery use a
different backend or add a Stream-based fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from .events import InboundMessage, OutboundMessage
from .queue import MessageBus

logger = logging.getLogger(__name__)

# Field keys — must match nats.py and zmq.py for wire compatibility
_FIELD_SESSION_KEY = "session_key"
_FIELD_CONTENT = "content"
_FIELD_SENDER = "sender"
_FIELD_METADATA = "metadata"
_FIELD_CHANNEL = "channel"
_FIELD_CHAT_ID = "chat_id"
_FIELD_SENDER_ID = "sender_id"

# Defaults
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_DEFAULT_CHANNEL_PREFIX = "nanobot:agent"


class RedisMessageBus(MessageBus):
    """Message bus using Redis pub/sub.

    Uses two Redis connections:
    - **Publisher** — shared connection for regular commands (PUBLISH).
    - **Subscriber** — dedicated connection for the blocking SUBSCRIBE loop.

    A background asyncio task reads incoming messages from the subscriber
    and feeds them into ``agent_inbound`` queue.
    """

    def __init__(
        self,
        redis_url: str = _DEFAULT_REDIS_URL,
        agent_id: str = "",
        channel_prefix: str = _DEFAULT_CHANNEL_PREFIX,
    ) -> None:
        super().__init__(agent_id=agent_id)
        self._redis_url = redis_url
        self._channel_prefix = channel_prefix

        # Connections
        self._pub_conn: aioredis.Redis | None = None
        self._sub_conn: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None

        # Background listener
        self._listener_task: asyncio.Task[None] | None = None

        # Derived channel names
        self._my_channel = f"{channel_prefix}:{agent_id}" if agent_id else ""
        self._broadcast_channel = f"{channel_prefix}:broadcast"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to Redis, subscribe, start background listener."""
        logger.info(
            "Redis bus connecting to %s (agent=%s)",
            self._redis_url, self._agent_id,
        )

        # Publisher connection
        self._pub_conn = await aioredis.from_url(
            self._redis_url,
            socket_connect_timeout=5,
            socket_keepalive=True,
        )
        await self._pub_conn.ping()
        logger.debug("Redis publisher connected")

        # Subscriber connection (dedicated — redis-py requires a separate
        # connection for pub/sub because SUBSCRIBE blocks the connection).
        self._sub_conn = await aioredis.from_url(
            self._redis_url,
            socket_connect_timeout=5,
            socket_keepalive=True,
        )
        self._pubsub = self._sub_conn.pubsub()

        # Subscribe
        channels_to_sub = [self._broadcast_channel]
        if self._my_channel:
            channels_to_sub.append(self._my_channel)

        await self._pubsub.subscribe(*channels_to_sub)
        logger.info(
            "Redis subscribed to %s",
            ", ".join(channels_to_sub),
        )

        # Start background listener
        self._listener_task = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        """Unsubscribe, stop listener, close connections."""
        # Stop listener first
        if self._listener_task is not None and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        # Unsubscribe and close pubsub
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe()
            except Exception:
                pass
            try:
                await self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None

        # Close connections
        for conn in (self._sub_conn, self._pub_conn):
            if conn is not None:
                try:
                    await conn.aclose()
                except Exception:
                    pass
        self._sub_conn = None
        self._pub_conn = None

        logger.info("Redis bus stopped")

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish_agent_message(self, msg: InboundMessage) -> None:
        """Publish a cross-instance message to the target agent's channel."""
        if self._pub_conn is None:
            logger.debug("Redis publish_agent_message: bus not started")
            return

        target_agent = (msg.metadata or {}).get("target_agent")
        if not target_agent:
            return

        # Serialize to JSON (same wire format as NATS)
        payload = self._serialize(msg)

        # Determine channel: broadcast or specific agent
        if target_agent == "*":
            channel = self._broadcast_channel
        else:
            channel = f"{self._channel_prefix}:{target_agent}"

        await self._pub_conn.publish(channel, payload)
        logger.debug(
            "Redis published on %s -> %s (content=%.60s)",
            channel, target_agent, msg.content,
        )

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Route inbound CLI/user message — local + cross-instance."""
        target = (msg.metadata or {}).get("target_agent")
        is_for_me = target is None or target == self._agent_id or target == "*"

        if is_for_me:
            await self.inbound.put(msg)

        if target is not None and target != self._agent_id:
            await self.publish_agent_message(msg)

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Route outbound response — local only (same as NATS)."""
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
    # Serialisation
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(msg: InboundMessage) -> str:
        fields = {
            _FIELD_SESSION_KEY: msg.session_key,
            _FIELD_CONTENT: msg.content or "",
            _FIELD_SENDER: msg.sender or "",
            _FIELD_CHANNEL: msg.channel or "bus",
            _FIELD_CHAT_ID: msg.chat_id or "",
            _FIELD_SENDER_ID: msg.sender_id or "",
            _FIELD_METADATA: json.dumps(msg.metadata or {}),
        }
        return json.dumps(fields)

    # ------------------------------------------------------------------
    # Background listener
    # ------------------------------------------------------------------

    async def _listen(self) -> None:
        """Background task: read pub/sub messages and enqueue as
        ``InboundMessage`` objects on ``agent_inbound``."""
        logger.debug("Redis listener started")
        try:
            async for message in self._pubsub.listen():  # type: ignore[union-attr]
                if message["type"] != "message":
                    continue

                data: bytes | str = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                inbound = self._deserialize(data)
                if inbound is None:
                    continue

                await self.agent_inbound.put(inbound)
                logger.debug(
                    "Redis received agent message from %s (len=%d)",
                    inbound.sender, len(inbound.content or ""),
                )
        except asyncio.CancelledError:
            logger.debug("Redis listener cancelled")
        except Exception:
            logger.exception("Redis listener error")
        finally:
            logger.debug("Redis listener stopped")

    @staticmethod
    def _deserialize(payload: str) -> InboundMessage | None:
        """Reconstruct an InboundMessage from JSON payload."""
        try:
            fields: dict[str, Any] = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Redis: invalid message payload: %s", exc)
            return None

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
