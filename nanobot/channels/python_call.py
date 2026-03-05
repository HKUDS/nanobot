"""Python call channel for programmatic access to nanobot."""

import asyncio
import uuid
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import PythonCallConfig


class PythonCallChannel(BaseChannel):
    """
    Channel that allows Python code to interact with nanobot programmatically.

    Usage::

        channel = manager.get_channel("python_call")
        response = await channel.call("Hello, nanobot!")

    Each ``call()`` publishes an inbound message to the bus, then waits for
    the corresponding outbound reply (matched by ``chat_id``).
    """

    name = "python_call"

    def __init__(self, config: PythonCallConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: PythonCallConfig = config
        # Pending futures keyed by chat_id, waiting for outbound responses
        self._pending: dict[str, asyncio.Future[str]] = {}

    async def start(self) -> None:
        """Mark the channel as running (no persistent connection needed)."""
        self._running = True
        logger.info("Python call channel started")

    async def stop(self) -> None:
        """Stop the channel and cancel any pending calls."""
        self._running = False
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        logger.info("Python call channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """
        Handle an outbound message from the agent.

        If the ``chat_id`` matches a pending call, resolve its future so that
        ``call()`` returns the response.  Progress messages (metadata
        ``_progress``) are silently ignored.
        """
        if msg.metadata.get("_progress"):
            return

        fut = self._pending.get(msg.chat_id)
        if fut and not fut.done():
            fut.set_result(msg.content)
        else:
            logger.debug(
                "python_call: no pending future for chat_id={}", msg.chat_id
            )

    async def call(
        self,
        content: str,
        *,
        sender_id: str = "python_caller",
        chat_id: str | None = None,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> str:
        """
        Send a message to the agent and wait for its response.

        Args:
            content: The message text to send.
            sender_id: Identifier for the caller (default ``"python_caller"``).
            chat_id: Optional chat identifier.  A unique id is generated when
                     omitted so that concurrent calls don't collide.
            media: Optional list of media URLs to attach.
            metadata: Optional extra metadata forwarded to the agent.
            timeout: Maximum seconds to wait for the agent's reply.
                     ``None`` means wait indefinitely.

        Returns:
            The agent's text response.

        Raises:
            asyncio.TimeoutError: If *timeout* is set and the agent does not
                reply in time.
            RuntimeError: If the channel is not running.
        """
        if not self._running:
            raise RuntimeError("python_call channel is not running")

        if chat_id is None:
            chat_id = f"pycall-{uuid.uuid4().hex[:12]}"

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[chat_id] = fut

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media,
                metadata=metadata,
            )

            if timeout is not None:
                return await asyncio.wait_for(fut, timeout=timeout)
            return await fut
        finally:
            self._pending.pop(chat_id, None)
