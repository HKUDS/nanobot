"""Discord channel implementation using discord.py 2.x."""

import asyncio
from pathlib import Path
from typing import Any, Literal

import discord
import httpx
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"


class DiscordChannel(BaseChannel):
    """Discord channel using discord.py 2.x."""

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
        self._client: discord.Client | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._http: httpx.AsyncClient | None = None
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        """Start the Discord client."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        intents = discord.Intents._from_value(self.config.intents)
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready() -> None:
            self._bot_user_id = str(self._client.user.id)
            logger.info("Discord ready as {}", self._client.user)

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            await self._handle_message_create(message)

        try:
            await self._client.start(self.config.token)
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        for task in self._typing_tasks.values():
            task.cancel()
        if self._typing_tasks:
            await asyncio.gather(*self._typing_tasks.values(), return_exceptions=True)
        self._typing_tasks.clear()
        if self._client:
            await self._client.close()
            self._client = None
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message via discord.py, including file attachments."""
        if not self._client:
            logger.warning("Discord client not initialized")
            return

        channel = self._client.get_channel(int(msg.chat_id))
        if channel is None:
            try:
                channel = await self._client.fetch_channel(int(msg.chat_id))
            except Exception as e:
                logger.error("Discord channel {} not found: {}", msg.chat_id, e)
                return

        try:
            sent_media = False
            failed_media: list[str] = []

            # Send file attachments first
            for media_path in msg.media or []:
                path = Path(media_path)
                if not path.is_file():
                    logger.warning("Discord file not found, skipping: {}", media_path)
                    failed_media.append(path.name)
                    continue
                if path.stat().st_size > MAX_ATTACHMENT_BYTES:
                    logger.warning("Discord file too large (>20MB), skipping: {}", path.name)
                    failed_media.append(path.name)
                    continue
                try:
                    reference = None
                    if msg.reply_to and not sent_media:
                        reference = discord.MessageReference(
                            message_id=int(msg.reply_to),
                            channel_id=int(msg.chat_id),
                            fail_if_not_exists=False,
                        )
                    await channel.send(
                        file=discord.File(path),
                        reference=reference,
                        mention_author=False,
                    )
                    sent_media = True
                    logger.info("Discord file sent: {}", path.name)
                except Exception as e:
                    logger.error("Error sending Discord file {}: {}", path.name, e)
                    failed_media.append(path.name)

            # Send text content
            chunks = split_message(msg.content or "", MAX_MESSAGE_LEN)
            if not chunks and failed_media and not sent_media:
                chunks = split_message(
                    "\n".join(f"[attachment: {name} - send failed]" for name in failed_media),
                    MAX_MESSAGE_LEN,
                )
            if not chunks:
                return

            for i, chunk in enumerate(chunks):
                reference = None
                if i == 0 and msg.reply_to and not sent_media:
                    reference = discord.MessageReference(
                        message_id=int(msg.reply_to),
                        channel_id=int(msg.chat_id),
                        fail_if_not_exists=False,
                    )
                try:
                    await channel.send(
                        content=chunk,
                        reference=reference,
                        mention_author=False,
                    )
                except Exception as e:
                    logger.error("Error sending Discord message: {}", e)
                    break  # Abort remaining chunks on failure
        finally:
            await self._stop_typing(msg.chat_id)

    async def _handle_message_create(self, message: discord.Message) -> None:
        """Handle incoming Discord messages."""
        if message.author.bot:
            return

        sender_id = str(message.author.id)
        channel_id = str(message.channel.id)
        content = message.content or ""
        guild_id = str(message.guild.id) if message.guild else None

        if not sender_id or not channel_id:
            return

        if not self.is_allowed(sender_id):
            return

        # Check group channel policy (DMs always respond if is_allowed passes)
        if guild_id is not None:
            if not self._should_respond_in_group(message, content):
                return

        content_parts = [content] if content else []
        media_paths: list[str] = []
        media_dir = get_media_dir("discord")

        for attachment in message.attachments:
            url = attachment.url
            filename = attachment.filename or "attachment"
            size = attachment.size or 0
            if not url or not self._http:
                continue
            if size and size > MAX_ATTACHMENT_BYTES:
                content_parts.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                file_path = media_dir / f"{attachment.id}_{filename.replace('/', '_')}"
                resp = await self._http.get(url)
                resp.raise_for_status()
                file_path.write_bytes(resp.content)
                media_paths.append(str(file_path))
                content_parts.append(f"[attachment: {file_path}]")
            except Exception as e:
                logger.warning("Failed to download Discord attachment: {}", e)
                content_parts.append(f"[attachment: {filename} - download failed]")

        reply_to = (
            str(message.reference.message_id)
            if message.reference and message.reference.message_id is not None
            else None
        )

        await self._start_typing(message.channel)

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content="\n".join(p for p in content_parts if p) or "[empty message]",
            media=media_paths,
            metadata={
                "message_id": str(message.id),
                "guild_id": guild_id,
                "reply_to": reply_to,
            },
        )

    def _should_respond_in_group(self, message: discord.Message, content: str) -> bool:
        """Check if bot should respond in a group channel based on policy."""
        if self.config.group_policy == "open":
            return True

        if self.config.group_policy == "mention":
            # Check if bot was mentioned in the message
            if self._bot_user_id:
                if any(str(m.id) == self._bot_user_id for m in message.mentions):
                    return True
                # Also check content for mention format <@USER_ID>
                if f"<@{self._bot_user_id}>" in content or f"<@!{self._bot_user_id}>" in content:
                    return True
            logger.debug("Discord message in {} ignored (bot not mentioned)", str(message.channel.id))
            return False

        return False

    async def _start_typing(self, channel: discord.abc.Messageable) -> None:
        """Start typing indicator for a channel using discord.py context manager."""
        channel_id = str(channel.id)  # type: ignore[attr-defined]
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            try:
                async with channel.typing():
                    await asyncio.sleep(float("inf"))  # keeps typing context open
            except (asyncio.CancelledError, Exception):
                pass

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator for a channel."""
        task = self._typing_tasks.pop(channel_id, None)
        if task:
            task.cancel()
