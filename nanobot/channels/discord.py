"""Discord channel implementation using discord.py."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import discord
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message

if TYPE_CHECKING:
    from discord.abc import Messageable

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit
TYPING_INTERVAL_S = 8


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"


class _DiscordClient(discord.Client):
    """discord.py client that forwards events to the owning channel."""

    def __init__(self, owner: "DiscordChannel", *, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self._owner = owner

    async def on_ready(self) -> None:
        self._owner._bot_user_id = str(self.user.id) if self.user else None
        logger.info("Discord bot connected as user {}", self._owner._bot_user_id)

    async def on_message(self, message: discord.Message) -> None:
        await self._owner._on_message(message)


class DiscordChannel(BaseChannel):
    """Discord channel using discord.py."""

    name = "discord"
    display_name = "Discord"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return DiscordConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = DiscordConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self._client: _DiscordClient | None = None
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        """Start the Discord client."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        try:
            intents = discord.Intents(self.config.intents)
            self._client = _DiscordClient(self, intents=intents)
        except Exception as e:
            logger.error("Failed to initialize Discord client: {}", e)
            self._client = None
            self._running = False
            return

        self._running = True
        logger.info("Starting Discord client via discord.py...")

        try:
            await self._client.start(self.config.token)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Discord client startup failed: {}", e)
        finally:
            self._running = False
            if self._client is not None and not self._client.is_closed():
                try:
                    await self._client.close()
                except Exception as e:
                    logger.warning("Discord client close failed: {}", e)
            self._client = None
            self._bot_user_id = None
            await self._cancel_all_typing()

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        await self._cancel_all_typing()
        if self._client is None:
            return
        try:
            if not self._client.is_closed():
                await self._client.close()
        except Exception as e:
            logger.warning("Discord client close failed: {}", e)
        finally:
            self._client = None
            self._bot_user_id = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord using discord.py."""
        client = self._client
        if client is None or not client.is_ready():
            logger.warning("Discord client not ready; dropping outbound message")
            return

        channel = client.get_channel(int(msg.chat_id))
        if channel is None:
            logger.warning("Discord channel {} not available in client cache", msg.chat_id)
            await self._stop_typing(msg.chat_id)
            return

        reference = self._build_reference(channel, msg.reply_to)
        mention_settings = discord.AllowedMentions(replied_user=False)
        sent_media = False
        failed_media: list[str] = []

        try:
            for index, media_path in enumerate(msg.media or []):
                if await self._send_file(
                    channel,
                    media_path,
                    reference=reference if index == 0 else None,
                    mention_settings=mention_settings,
                ):
                    sent_media = True
                else:
                    failed_media.append(Path(media_path).name)

            chunks = split_message(msg.content or "", MAX_MESSAGE_LEN)
            if not chunks and failed_media and not sent_media:
                chunks = split_message(
                    "\n".join(f"[attachment: {name} - send failed]" for name in failed_media),
                    MAX_MESSAGE_LEN,
                )
            if not chunks:
                return

            for index, chunk in enumerate(chunks):
                kwargs: dict[str, Any] = {"content": chunk}
                if index == 0 and reference is not None and not sent_media:
                    kwargs["reference"] = reference
                    kwargs["allowed_mentions"] = mention_settings
                await channel.send(**kwargs)
        except Exception as e:
            logger.error("Error sending Discord message: {}", e)
        finally:
            await self._stop_typing(msg.chat_id)

    async def _send_file(
        self,
        channel: "Messageable",
        file_path: str,
        *,
        reference: discord.PartialMessage | None,
        mention_settings: discord.AllowedMentions,
    ) -> bool:
        """Send a file attachment via discord.py."""
        path = Path(file_path)
        if not path.is_file():
            logger.warning("Discord file not found, skipping: {}", file_path)
            return False

        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            logger.warning("Discord file too large (>20MB), skipping: {}", path.name)
            return False

        try:
            kwargs: dict[str, Any] = {"file": discord.File(path)}
            if reference is not None:
                kwargs["reference"] = reference
                kwargs["allowed_mentions"] = mention_settings
            await channel.send(**kwargs)
            logger.info("Discord file sent: {}", path.name)
            return True
        except Exception as e:
            logger.error("Error sending Discord file {}: {}", path.name, e)
            return False

    async def _on_message(self, message: discord.Message) -> None:
        """Handle incoming Discord messages from discord.py."""
        if message.author.bot:
            return

        sender_id = str(message.author.id)
        channel_id = str(message.channel.id)
        guild_id = str(message.guild.id) if message.guild else None
        content = message.content or ""

        if not self.is_allowed(sender_id):
            return

        if message.guild is not None and not self._should_respond_in_group(message, content):
            return

        content_parts = [content] if content else []
        media_paths: list[str] = []
        media_dir = get_media_dir("discord")

        for attachment in message.attachments:
            filename = attachment.filename or "attachment"
            if attachment.size and attachment.size > MAX_ATTACHMENT_BYTES:
                content_parts.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                safe_name = filename.replace("/", "_")
                file_path = media_dir / f"{attachment.id}_{safe_name}"
                await attachment.save(file_path)
                media_paths.append(str(file_path))
                content_parts.append(f"[attachment: {file_path}]")
            except Exception as e:
                logger.warning("Failed to download Discord attachment: {}", e)
                content_parts.append(f"[attachment: {filename} - download failed]")

        reply_to = str(message.reference.message_id) if message.reference and message.reference.message_id else None

        await self._start_typing(message.channel)

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content="\n".join(part for part in content_parts if part) or "[empty message]",
            media=media_paths,
            metadata={
                "message_id": str(message.id),
                "guild_id": guild_id,
                "reply_to": reply_to,
            },
        )

    def _should_respond_in_group(self, message: discord.Message, content: str) -> bool:
        """Check if the bot should respond in a guild channel based on policy."""
        if self.config.group_policy == "open":
            return True

        if self.config.group_policy == "mention":
            bot_user_id = self._bot_user_id or (str(self._client.user.id) if self._client and self._client.user else None)
            if bot_user_id is None:
                logger.debug("Discord message in {} ignored (bot identity unavailable)", message.channel.id)
                return False

            if any(str(user.id) == bot_user_id for user in message.mentions):
                return True
            if f"<@{bot_user_id}>" in content or f"<@!{bot_user_id}>" in content:
                return True

            logger.debug("Discord message in {} ignored (bot not mentioned)", message.channel.id)
            return False

        return True

    async def _start_typing(self, channel: "Messageable") -> None:
        """Start periodic typing indicator for a channel."""
        channel_id = str(channel.id)
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            while self._running:
                try:
                    await channel.trigger_typing()
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.debug("Discord typing indicator failed for {}: {}", channel_id, e)
                    return
                await asyncio.sleep(TYPING_INTERVAL_S)

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator for a channel."""
        task = self._typing_tasks.pop(str(channel_id), None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _cancel_all_typing(self) -> None:
        """Stop all typing tasks."""
        channel_ids = list(self._typing_tasks)
        for channel_id in channel_ids:
            await self._stop_typing(channel_id)

    @staticmethod
    def _build_reference(
        channel: "Messageable",
        reply_to: str | None,
    ) -> discord.PartialMessage | None:
        """Build a lightweight reply reference when supported by the channel type."""
        if not reply_to:
            return None
        try:
            message_id = int(reply_to)
        except (TypeError, ValueError):
            logger.warning("Invalid Discord reply target: {}", reply_to)
            return None

        get_partial_message = getattr(channel, "get_partial_message", None)
        if callable(get_partial_message):
            return get_partial_message(message_id)

        logger.warning("Discord channel {} does not support replies", getattr(channel, "id", "?"))
        return None
