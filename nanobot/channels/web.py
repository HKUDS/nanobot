"""Web channel — bridges the FastAPI HTTP layer with the agent bus.

The web channel acts like any other channel (Telegram, Discord, etc.) but
instead of connecting to an external platform it serves the assistant-ui
React frontend.  Each HTTP request registers a per-thread
``asyncio.Queue`` and publishes an ``InboundMessage`` to the bus.  When
the agent publishes ``OutboundMessage`` responses (including streaming
progress updates) the dispatcher routes them to the matching queue so
the HTTP handler can yield them as SSE events.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class WebChannel(BaseChannel):
    """Request-driven channel for the web UI.

    Unlike long-running channels (Telegram, Discord) this channel is driven
    by incoming HTTP requests.  ``start()``/``stop()`` manage only the
    outbound dispatcher task which routes agent responses to per-request
    SSE streams.

    When *managed* is ``True`` the channel is owned by :class:`ChannelManager`
    which runs its own bus consumer.  In that case ``start()`` is a no-op
    (no private dispatcher) and messages arrive directly via ``send()``.
    """

    name: str = "web"

    def __init__(self, config: Any, bus: MessageBus, *, managed: bool = False) -> None:
        super().__init__(config, bus)
        # chat_id → queue of outbound messages for that thread's SSE stream
        self._streams: dict[str, asyncio.Queue[OutboundMessage | None]] = {}
        # chat_ids whose SSE stream was closed (client disconnect / stop button).
        # Messages for these are silently dropped to avoid log spam from the
        # agent loop which may still be running.
        self._disconnected: set[str] = set()
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._managed = managed

    # ------------------------------------------------------------------
    # BaseChannel interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the outbound dispatcher that routes responses to SSE streams.

        In managed mode the ChannelManager dispatcher calls ``send()``
        directly, so we skip the private dispatcher.
        """
        self._running = True
        if not self._managed:
            self._dispatcher_task = asyncio.create_task(self._dispatch_outbound())

    async def stop(self) -> None:
        """Stop the outbound dispatcher."""
        self._running = False
        if self._dispatcher_task and not self._dispatcher_task.done():
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def send(self, msg: OutboundMessage) -> None:
        """Route an outbound message to the SSE stream for its chat_id.

        Called by the dispatcher — not by external code directly.
        """
        q = self._streams.get(msg.chat_id)
        if q is not None:
            await q.put(msg)
        elif msg.chat_id in self._disconnected:
            pass  # silently drop — client already disconnected
        else:
            logger.debug("web: no active stream for chat_id={}", msg.chat_id)

    # ------------------------------------------------------------------
    # HTTP ↔ bus bridge
    # ------------------------------------------------------------------

    def register_stream(self, chat_id: str) -> asyncio.Queue[OutboundMessage | None]:
        """Register an SSE stream for *chat_id* and return its queue."""
        q: asyncio.Queue[OutboundMessage | None] = asyncio.Queue()
        self._streams[chat_id] = q
        self._disconnected.discard(chat_id)
        return q

    def unregister_stream(self, chat_id: str) -> None:
        """Remove the SSE stream registration for *chat_id*."""
        self._streams.pop(chat_id, None)
        self._disconnected.add(chat_id)

    async def publish_user_message(
        self,
        chat_id: str,
        content: str,
        *,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Publish a user message to the bus as an ``InboundMessage``."""
        session_key = f"web:{chat_id}"
        await self._handle_message(
            sender_id="user",
            chat_id=chat_id,
            content=content,
            media=media,
            metadata=metadata,
            session_key=session_key,
        )

    # ------------------------------------------------------------------
    # Outbound dispatcher (mirrors ChannelManager._dispatch_outbound)
    # ------------------------------------------------------------------

    async def _dispatch_outbound(self) -> None:
        """Consume outbound messages from the bus and route web messages to SSE streams."""
        logger.info("Web outbound dispatcher started")
        while self._running:
            try:
                # Block until a message is available — no timeout needed because
                # task cancellation (via stop) handles shutdown cleanly.
                msg = await self.bus.consume_outbound()

                if msg.channel != self.name:
                    # Not for us — in a full gateway the ChannelManager handles
                    # other channels.  In the UI-only mode we just drop them.
                    logger.debug("web dispatcher: ignoring channel={}", msg.channel)
                    continue

                await self.send(msg)

            except asyncio.CancelledError:
                break
            except Exception:  # crash-barrier: keep dispatcher alive
                logger.opt(exception=True).warning("Web dispatcher error")
                continue
