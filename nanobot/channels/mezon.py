"""Mezon channel implementation using mezon-sdk with handler-based architecture."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, List
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import MezonConfig


def _split_message(content: str, max_len: int = 2000) -> list[str]:
    """Split content into chunks within max_len, preferring line breaks."""
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        pos = cut.rfind("\n")
        if pos == -1:
            pos = cut.rfind(" ")
        if pos == -1:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


class BaseMessageHandler(ABC):
    """Base class for message handlers following the template pattern."""

    def __init__(self, bot_id: str):
        self.bot_id = bot_id

    @abstractmethod
    def get_command(self) -> str:
        """Return the command this handler responds to."""

    @abstractmethod
    async def handle(self, message: Any, content: str) -> None:
        """Handle the incoming message."""

    def should_handle(self, content: str) -> bool:
        """Determine if this handler should process the message."""
        command = self.get_command()
        return content.strip().lower().startswith(command.lower())

    async def send_message(self, channel: Any, content: str, **kwargs) -> None:
        """Send a message to the channel."""
        try:
            from mezon import ChannelMessageContent
            await channel.send(content=ChannelMessageContent(t=content), **kwargs)
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    async def reply_message(self, channel: Any, content: str, **kwargs) -> None:
        """Reply to a message."""
        await self.send_message(channel, content, **kwargs)


class HandlerManager:
    """Manages and routes messages to appropriate handlers."""

    def __init__(self, client_id: str, allow_from: list[str] | None = None):
        self.client_id = client_id
        self.allow_from = allow_from or []
        self.handlers: List[BaseMessageHandler] = []

    def register_handler(self, handler: BaseMessageHandler) -> None:
        """Register a new message handler."""
        self.handlers.append(handler)
        logger.info(f"Registered handler: {handler.__class__.__name__} for command: {handler.get_command()}")

    def _is_sender_allowed(self, sender_id: str) -> bool:
        """Check if sender is allowed based on allow_from list."""
        if not self.allow_from:
            return True  # No restrictions

        # Convert sender_id to string for comparison
        sender_id_str = str(sender_id)
        return sender_id_str in self.allow_from

    async def handle_message(self, message: Any) -> None:
        """Route an incoming message to the appropriate handler."""
        try:
            # Filter out self-sent messages
            if getattr(message, "sender_id", "") == self.client_id:
                return

            # Check if sender is allowed
            sender_id = getattr(message, "sender_id", "")
            if not self._is_sender_allowed(sender_id):
                logger.debug(f"Sender {sender_id} not in allow_from list, ignoring message")
                return

            # Parse message content
            raw_content = getattr(message, "content", None)
            content = ""
            if raw_content:
                try:
                    if isinstance(raw_content, (bytes, bytearray)):
                        raw_content = raw_content.decode("utf-8")
                    data = json.loads(raw_content)
                    content = data.get("t") or ""
                except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
                    content = str(raw_content)

            if not content.strip():
                return

            # Route to appropriate handler
            for handler in self.handlers:
                if handler.should_handle(content):
                    logger.info(f"Routing to {handler.__class__.__name__} for command: {handler.get_command()}")
                    await handler.handle(message, content)
                    break

        except Exception as e:
            logger.error(f"Error in HandlerManager.handle_message: {e}")


class DefaultHandler(BaseMessageHandler):
    """Default handler that processes all messages when no specific handler matches."""

    def get_command(self) -> str:
        return "*"

    def should_handle(self, content: str) -> bool:
        return True

    async def handle(self, message: Any, content: str) -> None:
        """Handle the message by logging it (default behavior)."""
        sender_id = getattr(message, "sender_id", "")
        channel_id = getattr(message, "channel_id", "")
        logger.debug(f"Default handler processing message from {sender_id} in {channel_id}: {content[:60]}...")


class MezonChannel(BaseChannel):
    """
    Mezon channel using mezon-sdk WebSocket connection with handler-based architecture.

    No public IP required — uses persistent WebSocket with auto-reconnect.
    """

    name = "mezon"

    def __init__(self, config: MezonConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: MezonConfig = config
        self._client = None
        self.handler_manager = HandlerManager(str(config.bot_id), config.allow_from)

        # Register default handler
        self.handler_manager.register_handler(DefaultHandler(str(config.bot_id)))

    async def start(self) -> None:
        """Start the Mezon bot connection."""
        if not self.config.bot_id or not self.config.bot_token:
            logger.error("Mezon bot_id and bot_token must be configured")
            return

        from mezon import MezonClient

        self._running = True
        reconnect_delay = 5

        while self._running:
            try:
                self._client = MezonClient(
                    client_id=self.config.bot_id,
                    api_key=self.config.bot_token,
                )

                self._client.on_channel_message(self._on_message)

                # The ZK proof step in login() is for token transfers only (not needed
                # for basic messaging) and may fail for bot accounts. Skip it safely.
                async def _skip_zk_proof() -> None:
                    return None  # type: ignore[return-value]

                self._client.get_zk_proof = _skip_zk_proof  # type: ignore[method-assign]

                logger.info("Connecting to Mezon...")
                await self._client.login(enable_auto_reconnect=True)
                logger.info(f"Mezon bot connected (bot_id={self.config.bot_id})")
                logger.info(f"Registered {len(self.handler_manager.handlers)} message handlers")

                # Log allow_from settings
                if self.handler_manager.allow_from:
                    logger.info(f"Allow_from filter enabled for {len(self.handler_manager.allow_from)} users")
                else:
                    logger.info("Allow_from filter disabled (accepting messages from all users)")

                # Keep alive — SDK maintains the connection via internal tasks
                while self._running:
                    await asyncio.sleep(5)
                    # If SDK exhausted its reconnect retries, restart from scratch
                    if self._client and not await self._client.socket_manager.is_connected():
                        logger.warning("Mezon socket lost, restarting connection...")
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                logger.warning(f"Mezon connection error: {e}. Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def stop(self) -> None:
        """Stop the Mezon bot connection."""
        self._running = False
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.debug(f"Mezon disconnect: {e}")
            self._client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to a Mezon channel."""
        if not self._client:
            logger.warning("Mezon client not running")
            return

        if not msg.content or msg.content == "[empty message]":
            return

        try:
            from mezon import ChannelMessageContent
            channel = await self._client.channels.fetch(int(msg.chat_id))
            for chunk in _split_message(msg.content):
                await channel.send(content=ChannelMessageContent(t=chunk))
        except Exception as e:
            logger.error(f"Error sending Mezon message to {msg.chat_id}: {e}")

    async def _on_message(self, message) -> None:
        """Handle an incoming Mezon channel message using the handler manager."""
        try:
            logger.info(f"message received: {message}")
            # Use handler manager to route the message
            await self.handler_manager.handle_message(message)

            # Also forward to the bus for existing nanobot functionality
            sender_id = str(getattr(message, "sender_id", "") or "")
            channel_id = str(getattr(message, "channel_id", "") or "")

            if not sender_id or not channel_id:
                return

            # Ignore messages from the bot itself
            if sender_id == str(self.config.bot_id):
                return

            # Parse message content (JSON {"t": "text", ...})
            raw_content = getattr(message, "content", None)
            content = ""
            if raw_content:
                try:
                    if isinstance(raw_content, (bytes, bytearray)):
                        raw_content = raw_content.decode("utf-8")
                    data = json.loads(raw_content)
                    content = data.get("t") or ""
                except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
                    content = str(raw_content)

            if not content.strip():
                return

            logger.debug(f"Mezon message from {sender_id} in {channel_id}: {content[:60]}...")

            await self._handle_message(
                sender_id=sender_id,
                chat_id=channel_id,
                content=content,
                metadata={
                    "message_id": str(getattr(message, "id", "") or ""),
                    "clan_id": str(getattr(message, "clan_id", "") or ""),
                    "channel_type": getattr(message, "channel_type", 0),
                    "username": str(getattr(message, "username", "") or ""),
                },
            )
        except Exception as e:
            logger.error(f"Error handling Mezon message: {e}")

    def register_handler(self, handler: BaseMessageHandler) -> None:
        """Register a custom message handler."""
        self.handler_manager.register_handler(handler)