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

        # One-off call (no session persistence)
        response = await channel.call("Hello, nanobot!")

        # Persistent session (conversation history preserved across calls)
        response1 = await channel.call("My name is Alice", session_id="alice")
        response2 = await channel.call("What's my name?", session_id="alice")

        # Config overrides via metadata
        response = await channel.call(
            "Translate to French",
            session_id="translator",
            metadata={"system_prompt": "You are a translator."},
        )

        # With timeout (raises asyncio.TimeoutError if agent doesn't reply)
        response = await channel.call("Hello", timeout=30.0)

    Each ``call()`` publishes an inbound message to the bus, then waits for
    the corresponding outbound reply (matched by ``chat_id``).

    .. warning::
        When *timeout* is not set (the default), ``call()`` blocks
        indefinitely until the agent replies.  Always consider setting a
        timeout in production code.
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
        session_id: str | None = None,
        session_key: str | None = None,
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
            session_id: Stable session identifier for conversation persistence.
                        When provided, the same ``session_id`` across multiple
                        calls keeps conversation history (the agent remembers
                        prior messages).  Mutually exclusive with ``chat_id``.
            session_key: Optional session key override passed to the bus.
                         Allows custom session scoping (e.g. sharing a session
                         across different chat_ids).
            media: Optional list of media URLs to attach.
            metadata: Optional extra metadata forwarded to the agent.  Config
                      overrides can be passed here (e.g. ``system_prompt``,
                      ``model``).
            timeout: Maximum seconds to wait for the agent's reply.
                     ``None`` means wait indefinitely.

        Returns:
            The agent's text response.

        Raises:
            asyncio.TimeoutError: If *timeout* is set and the agent does not
                reply in time.
            RuntimeError: If the channel is not running.
            ValueError: If both *chat_id* and *session_id* are provided.
        """
        if not self._running:
            raise RuntimeError("python_call channel is not running")

        if chat_id is not None and session_id is not None:
            raise ValueError("chat_id and session_id are mutually exclusive")

        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve the effective chat_id
        if session_id is not None:
            effective_chat_id = f"session-{session_id}"
        elif chat_id is not None:
            effective_chat_id = chat_id
        elif self.config.default_session_id:
            effective_chat_id = f"session-{self.config.default_session_id}"
        else:
            effective_chat_id = f"pycall-{uuid.uuid4().hex[:12]}"

        logger.debug(
            "python_call: call from {} chat_id={} content={}...",
            sender_id,
            effective_chat_id,
            content[:50],
        )

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending[effective_chat_id] = fut

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=effective_chat_id,
                content=content,
                media=media,
                metadata=metadata,
                session_key=session_key,
            )

            if timeout is not None:
                result = await asyncio.wait_for(fut, timeout=timeout)
            else:
                result = await fut

            logger.debug(
                "python_call: response for chat_id={} len={}",
                effective_chat_id,
                len(result),
            )
            return result
        finally:
            self._pending.pop(effective_chat_id, None)
