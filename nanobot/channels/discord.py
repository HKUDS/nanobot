"""Discord channel implementation using discord.py."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import discord
from discord import app_commands
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import safe_filename, split_message

if TYPE_CHECKING:
    from discord.abc import Messageable

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit
HELP_TEXT = (
    "nanobot commands:\n"
    "/new - Start a new conversation\n"
    "/help - Show available commands"
)


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"
    typing_interval_s: int = 8


class DiscordBotClient(discord.Client):
    """discord.py client that forwards events to the channel."""

    def __init__(self, channel: DiscordChannel, *, intents: discord.Intents) -> None:
        super().__init__(intents=intents)
        self._channel = channel
        self.tree = app_commands.CommandTree(self)
        self._register_app_commands()

    async def on_ready(self) -> None:
        self._channel._bot_user_id = str(self.user.id) if self.user else None
        logger.info("Discord bot connected as user {}", self._channel._bot_user_id)
        try:
            synced = await self.tree.sync()
            logger.info("Discord app commands synced: {}", len(synced))
        except Exception as e:
            logger.warning("Discord app command sync failed: {}", e)

    async def on_message(self, message: discord.Message) -> None:
        await self._channel._handle_discord_message(message)

    async def _reply_ephemeral(self, interaction: discord.Interaction, text: str) -> bool:
        """Send an ephemeral interaction response and report success."""
        try:
            await interaction.response.send_message(text, ephemeral=True)
            return True
        except Exception as e:
            logger.warning("Discord interaction response failed: {}", e)
            return False

    def _register_app_commands(self) -> None:
        @self.tree.command(name="new", description="Start a new conversation")
        async def new_command(interaction: discord.Interaction) -> None:
            user = interaction.user
            channel_id = interaction.channel_id
            sender_id = str(user.id)

            if not self._channel.is_allowed(sender_id):
                await self._reply_ephemeral(interaction, "You are not allowed to use this bot.")
                return

            if not await self._reply_ephemeral(interaction, "Starting a new session..."):
                return

            await self._channel._handle_message(
                sender_id=sender_id,
                chat_id=str(channel_id),
                content="/new",
                metadata={
                    "interaction_id": str(interaction.id),
                    "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                    "is_slash_command": True,
                },
            )

        @self.tree.command(name="help", description="Show available commands")
        async def help_command(interaction: discord.Interaction) -> None:
            await self._reply_ephemeral(interaction, HELP_TEXT)

        @self.tree.error
        async def on_app_command_error(
            interaction: discord.Interaction,
            error: app_commands.AppCommandError,
        ) -> None:
            logger.warning(
                "Discord app command failed user={} channel={} cmd={} error={}",
                getattr(getattr(interaction, "user", None), "id", "?"),
                getattr(interaction, "channel_id", "?"),
                getattr(getattr(interaction, "command", None), "qualified_name", "?"),
                error,
            )

    async def send_outbound(self, msg: OutboundMessage) -> None:
        """Send a nanobot outbound message using Discord transport rules."""
        try:
            channel_id = int(msg.chat_id)
        except (TypeError, ValueError):
            logger.warning("Invalid Discord channel id: {}", msg.chat_id)
            return

        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except Exception as e:
                logger.warning("Discord channel {} unavailable: {}", msg.chat_id, e)
                return

        reference, mention_settings = self._build_reply_context(channel, msg.reply_to)
        sent_media = False
        failed_media: list[str] = []

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

        for index, chunk in enumerate(self._build_chunks(msg.content or "", failed_media, sent_media)):
            kwargs: dict[str, Any] = {"content": chunk}
            if index == 0 and reference is not None and not sent_media:
                kwargs["reference"] = reference
                kwargs["allowed_mentions"] = mention_settings
            await channel.send(**kwargs)

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

    @staticmethod
    def _build_chunks(content: str, failed_media: list[str], sent_media: bool) -> list[str]:
        """Build outbound text chunks, including attachment-failure fallback text."""
        chunks = split_message(content, MAX_MESSAGE_LEN)
        if chunks or not failed_media or sent_media:
            return chunks
        fallback = "\n".join(f"[attachment: {name} - send failed]" for name in failed_media)
        return split_message(fallback, MAX_MESSAGE_LEN)

    @staticmethod
    def _build_reply_context(
        channel: "Messageable",
        reply_to: str | None,
    ) -> tuple[discord.PartialMessage | None, discord.AllowedMentions]:
        """Build reply context for outbound messages."""
        mention_settings = discord.AllowedMentions(replied_user=False)
        if not reply_to:
            return None, mention_settings
        try:
            message_id = int(reply_to)
        except (TypeError, ValueError):
            logger.warning("Invalid Discord reply target: {}", reply_to)
            return None, mention_settings

        get_partial_message = getattr(channel, "get_partial_message", None)
        if callable(get_partial_message):
            return get_partial_message(message_id), mention_settings

        logger.warning("Discord channel {} does not support replies", getattr(channel, "id", "?"))
        return None, mention_settings


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
        self._client: DiscordBotClient | None = None
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        """Start the Discord client."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        try:
            intents = discord.Intents.none()
            intents.value = self.config.intents
            self._client = DiscordBotClient(self, intents=intents)
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
            await self._reset_runtime_state(close_client=True)

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        await self._reset_runtime_state(close_client=True)

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord using discord.py."""
        client = self._client
        if client is None or not client.is_ready():
            logger.warning("Discord client not ready; dropping outbound message")
            return

        is_progress = bool((msg.metadata or {}).get("_progress"))
        try:
            await client.send_outbound(msg)
        except Exception as e:
            logger.error("Error sending Discord message: {}", e)
        finally:
            if not is_progress:
                await self._stop_typing(msg.chat_id)

    async def _handle_discord_message(self, message: discord.Message) -> None:
        """Handle incoming Discord messages from discord.py."""
        if message.author.bot:
            return

        sender_id = str(message.author.id)
        channel_id = str(message.channel.id)
        content = message.content or ""

        if not self._should_accept_inbound(message, sender_id, content):
            return

        media_paths, attachment_markers = await self._download_attachments(message.attachments)
        full_content = self._compose_inbound_content(content, attachment_markers)
        metadata = self._build_inbound_metadata(message)

        await self._start_typing(message.channel)

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=channel_id,
                content=full_content,
                media=media_paths,
                metadata=metadata,
            )
        except Exception:
            await self._stop_typing(channel_id)
            raise

    async def _on_message(self, message: discord.Message) -> None:
        """Backward-compatible alias for legacy tests/callers."""
        await self._handle_discord_message(message)

    def _should_accept_inbound(
        self,
        message: discord.Message,
        sender_id: str,
        content: str,
    ) -> bool:
        """Check if inbound Discord message should be processed."""
        if not self.is_allowed(sender_id):
            return False
        if message.guild is not None and not self._should_respond_in_group(message, content):
            return False
        return True

    async def _download_attachments(
        self,
        attachments: list[discord.Attachment],
    ) -> tuple[list[str], list[str]]:
        """Download supported attachments and return paths + display markers."""
        media_paths: list[str] = []
        markers: list[str] = []
        media_dir = get_media_dir("discord")

        for attachment in attachments:
            filename = attachment.filename or "attachment"
            if attachment.size and attachment.size > MAX_ATTACHMENT_BYTES:
                markers.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                safe_name = safe_filename(filename)
                file_path = media_dir / f"{attachment.id}_{safe_name}"
                await attachment.save(file_path)
                media_paths.append(str(file_path))
                markers.append(f"[attachment: {file_path.name}]")
            except Exception as e:
                logger.warning("Failed to download Discord attachment: {}", e)
                markers.append(f"[attachment: {filename} - download failed]")

        return media_paths, markers

    @staticmethod
    def _compose_inbound_content(content: str, attachment_markers: list[str]) -> str:
        """Combine message text with attachment markers."""
        content_parts = [content] if content else []
        content_parts.extend(attachment_markers)
        return "\n".join(part for part in content_parts if part) or "[empty message]"

    @staticmethod
    def _build_inbound_metadata(message: discord.Message) -> dict[str, str | None]:
        """Build metadata for inbound Discord messages."""
        reply_to = str(message.reference.message_id) if message.reference and message.reference.message_id else None
        return {
            "message_id": str(message.id),
            "guild_id": str(message.guild.id) if message.guild else None,
            "reply_to": reply_to,
        }

    def _should_respond_in_group(self, message: discord.Message, content: str) -> bool:
        """Check if the bot should respond in a guild channel based on policy."""
        if self.config.group_policy == "open":
            return True

        if self.config.group_policy == "mention":
            bot_user_id = self._bot_user_id
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
                    trigger_typing = getattr(channel, "trigger_typing", None)
                    if callable(trigger_typing):
                        await trigger_typing()
                    else:
                        typing_factory = getattr(channel, "typing", None)
                        if not callable(typing_factory):
                            raise AttributeError(
                                f"Channel {getattr(channel, 'id', '?')} does not support typing indicator"
                            )
                        async with typing_factory():
                            pass
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.debug("Discord typing indicator failed for {}: {}", channel_id, e)
                    return
                await asyncio.sleep(self.config.typing_interval_s)

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

    async def _reset_runtime_state(self, close_client: bool) -> None:
        """Reset client and typing state."""
        await self._cancel_all_typing()
        if close_client and self._client is not None and not self._client.is_closed():
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("Discord client close failed: {}", e)
        self._client = None
        self._bot_user_id = None
