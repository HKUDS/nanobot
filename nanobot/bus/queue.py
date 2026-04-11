"""Async message queue for decoupled channel-agent communication."""

from __future__ import annotations

import asyncio
import re
from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage

_WS_RE = re.compile(r"\s+")


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self, *, inbound_queue_dedup: bool = True):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._inbound_queue_dedup = inbound_queue_dedup
        # (session_key, normalized_body): in inbound queue or being processed by the agent
        self._inbound_dedup_keys: set[tuple[str, str]] = set()

    @staticmethod
    def _normalize_inbound_body(text: str) -> str:
        s = text.strip()
        if not s:
            return ""
        return _WS_RE.sub(" ", s).casefold()

    @classmethod
    def _inbound_dedup_key(cls, msg: InboundMessage) -> tuple[str, str] | None:
        """Return a key for queue deduplication, or None when this message must not be coalesced."""
        if msg.metadata.get("_skip_inbound_dedup"):
            return None
        raw = msg.content.strip()
        if raw.startswith("/"):
            return None
        body = cls._normalize_inbound_body(msg.content)
        if not body:
            return None
        return (msg.session_key, body)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        key = (
            self._inbound_dedup_key(msg)
            if self._inbound_queue_dedup
            else None
        )
        if key is not None and key in self._inbound_dedup_keys:
            logger.debug(
                "Skipping duplicate inbound (same text queued or in flight): session={} preview={!r}",
                key[0],
                key[1][:80] + ("…" if len(key[1]) > 80 else ""),
            )
            return
        if key is not None:
            self._inbound_dedup_keys.add(key)
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    def release_inbound_dedup(self, msg: InboundMessage) -> None:
        """Clear the dedup slot after this message has finished processing (call from a finally block)."""
        if not self._inbound_queue_dedup:
            return
        rk = self._inbound_dedup_key(msg)
        if rk is not None:
            self._inbound_dedup_keys.discard(rk)

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
