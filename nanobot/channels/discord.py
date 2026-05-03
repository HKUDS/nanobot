"""Discord channel implementation using discord.py."""

from __future__ import annotations

import asyncio
import importlib.util
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.command.builtin import build_help_text
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import safe_filename, split_message

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if TYPE_CHECKING:
    import aiohttp
    import discord
    from discord import app_commands
    from discord.abc import Messageable

if DISCORD_AVAILABLE:
    import discord
    from discord import app_commands
    from discord.abc import Messageable

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit
TYPING_INTERVAL_S = 8


@dataclass
class _StreamBuf:
    """Per-chat streaming accumulator for progressive Discord message edits."""

    text: str = ""
    message: Any | None = None
    last_edit: float = 0.0
    stream_id: str | None = None


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    allow_channels: list[str] = Field(default_factory=list)  # Allowed channel IDs (empty = all)
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"
    read_receipt_emoji: str = "👀"
    working_emoji: str = "🔧"
    working_emoji_delay: float = 2.0
    streaming: bool = True
    proxy: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None


if DISCORD_AVAILABLE:

    class DiscordBotClient(discord.Client):
        """discord.py client that forwards events to the channel."""

        def __init__(
            self,
            channel: DiscordChannel,
            *,
            intents: discord.Intents,
            proxy: str | None = None,
            proxy_auth: aiohttp.BasicAuth | None = None,
        ) -> None:
            super().__init__(intents=intents, proxy=proxy, proxy_auth=proxy_auth)
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

        async def on_thread_delete(self, thread: discord.Thread) -> None:
            self._channel._forget_channel(thread)

        async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
            if getattr(after, "archived", False):
                self._channel._forget_channel(after)
            else:
                self._channel._remember_channel(after)

        async def _reply_ephemeral(self, interaction: discord.Interaction, text: str) -> bool:
            """Send an ephemeral interaction response and report success."""
            try:
                await interaction.response.send_message(text, ephemeral=True)
                return True
            except Exception as e:
                logger.warning("Discord interaction response failed: {}", e)
                return False

        async def _resolve_interaction_channel(
            self,
            interaction: discord.Interaction,
        ) -> Any | None:
            channel_id = interaction.channel_id
            if channel_id is None:
                return None
            channel = getattr(interaction, "channel", None) or self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    logger.warning("Discord interaction channel {} unavailable: {}", channel_id, e)
                    return None
            self._channel._remember_channel(channel)
            return channel

        async def _interaction_channel_allowed(
            self,
            interaction: discord.Interaction,
            channel: Any | None,
        ) -> bool:
            allow_channels = self._channel.config.allow_channels
            if not allow_channels:
                return True
            if channel is None:
                channel_id = interaction.channel_id
                return channel_id is not None and str(channel_id) in allow_channels
            channel_ids = self._channel._channel_allow_keys(channel)
            return not channel_ids.isdisjoint(allow_channels)

        async def _forward_slash_command(
            self,
            interaction: discord.Interaction,
            command_text: str,
        ) -> None:
            sender_id = str(interaction.user.id)
            channel_id = interaction.channel_id

            if channel_id is None:
                logger.warning("Discord slash command missing channel_id: {}", command_text)
                return

            if not self._channel.is_allowed(sender_id):
                await self._reply_ephemeral(interaction, "You are not allowed to use this bot.")
                return

            channel = await self._resolve_interaction_channel(interaction)
            if not await self._interaction_channel_allowed(interaction, channel):
                await self._reply_ephemeral(interaction, "This channel is not allowed for this bot.")
                return

            await self._reply_ephemeral(interaction, f"Processing {command_text}...")

            metadata: dict[str, Any] = {
                "interaction_id": str(interaction.id),
                "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                "is_slash_command": True,
            }
            session_key = None
            if channel is not None:
                parent_channel_id = self._channel._channel_parent_key(channel)
                if parent_channel_id is not None:
                    metadata["parent_channel_id"] = parent_channel_id
                    metadata["context_chat_id"] = parent_channel_id
                    metadata["thread_id"] = str(channel_id)
                    session_key = f"{self._channel.name}:{parent_channel_id}:thread:{channel_id}"

            await self._channel._handle_message(
                sender_id=sender_id,
                chat_id=str(channel_id),
                content=command_text,
                metadata=metadata,
                session_key=session_key,
            )

        def _register_app_commands(self) -> None:
            commands = (
                ("new", "Stop current task and start a new conversation", "/new"),
                ("stop", "Stop the current task", "/stop"),
                ("restart", "Restart the bot", "/restart"),
                ("status", "Show bot status", "/status"),
                ("history", "Show recent conversation messages", "/history"),
            )

            for name, description, command_text in commands:

                @self.tree.command(name=name, description=description)
                async def command_handler(
                    interaction: discord.Interaction,
                    _command_text: str = command_text,
                ) -> None:
                    await self._forward_slash_command(interaction, _command_text)

            @self.tree.command(name="help", description="Show available commands")
            async def help_command(interaction: discord.Interaction) -> None:
                sender_id = str(interaction.user.id)
                if not self._channel.is_allowed(sender_id):
                    await self._reply_ephemeral(interaction, "You are not allowed to use this bot.")
                    return
                channel = await self._resolve_interaction_channel(interaction)
                if not await self._interaction_channel_allowed(interaction, channel):
                    await self._reply_ephemeral(interaction, "This channel is not allowed for this bot.")
                    return
                await self._reply_ephemeral(interaction, build_help_text())

            @self.tree.error
            async def on_app_command_error(
                interaction: discord.Interaction,
                error: app_commands.AppCommandError,
            ) -> None:
                command_name = interaction.command.qualified_name if interaction.command else "?"
                logger.warning(
                    "Discord app command failed user={} channel={} cmd={} error={}",
                    interaction.user.id,
                    interaction.channel_id,
                    command_name,
                    error,
                )

        async def send_outbound(self, msg: OutboundMessage) -> None:
            """Send a nanobot outbound message using Discord transport rules."""
            channel_id = int(msg.chat_id)

            channel = self._channel._known_channels.get(msg.chat_id) or self.get_channel(channel_id)
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

            for index, chunk in enumerate(
                self._build_chunks(msg.content or "", failed_media, sent_media)
            ):
                kwargs: dict[str, Any] = {"content": chunk}
                if index == 0 and reference is not None and not sent_media:
                    kwargs["reference"] = reference
                    kwargs["allowed_mentions"] = mention_settings
                await channel.send(**kwargs)

        async def _send_file(
            self,
            channel: Messageable,
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
            channel: Messageable,
            reply_to: str | None,
        ) -> tuple[discord.PartialMessage | None, discord.AllowedMentions]:
            """Build reply context for outbound messages."""
            mention_settings = discord.AllowedMentions(replied_user=False)
            if not reply_to:
                return None, mention_settings
            try:
                message_id = int(reply_to)
            except ValueError:
                logger.warning("Invalid Discord reply target: {}", reply_to)
                return None, mention_settings

            return channel.get_partial_message(message_id), mention_settings


class DiscordChannel(BaseChannel):
    """Discord channel using discord.py."""

    name = "discord"
    display_name = "Discord"
    _STREAM_EDIT_INTERVAL = 0.8

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return DiscordConfig().model_dump(by_alias=True)

    @staticmethod
    def _channel_key(channel_or_id: Any) -> str:
        """Normalize channel-like objects and ids to a stable string key."""
        channel_id = getattr(channel_or_id, "id", channel_or_id)
        return str(channel_id)

    @classmethod
    def _channel_allow_keys(cls, channel: Any) -> set[str]:
        """Return channel IDs that can satisfy allow_channels for this channel."""
        keys = {cls._channel_key(channel)}
        if parent_key := cls._channel_parent_key(channel):
            keys.add(parent_key)
        return keys

    @classmethod
    def _channel_parent_key(cls, channel: Any) -> str | None:
        """Return the parent channel key for a Discord thread-like channel."""
        parent_id = getattr(channel, "parent_id", None)
        if parent_id is not None:
            return cls._channel_key(parent_id)
        parent = getattr(channel, "parent", None)
        if parent is not None:
            return cls._channel_key(parent)
        return None

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = DiscordConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self._client: DiscordBotClient | None = None
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._bot_user_id: str | None = None
        self._pending_reactions: dict[str, Any] = {}  # chat_id -> message object
        self._working_emoji_tasks: dict[str, asyncio.Task[None]] = {}
        self._stream_bufs: dict[str, _StreamBuf] = {}
        self._known_channels: dict[str, Any] = {}

    def _remember_channel(self, channel: Any) -> None:
        self._known_channels[self._channel_key(channel)] = channel

    def _forget_channel(self, channel_or_id: Any) -> None:
        self._known_channels.pop(self._channel_key(channel_or_id), None)

    async def start(self) -> None:
        """Start the Discord client."""
        if not DISCORD_AVAILABLE:
            logger.error("discord.py not installed. Run: pip install nanobot-ai[discord]")
            return

        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        try:
            intents = discord.Intents.none()
            intents.value = self.config.intents

            proxy_auth = None
            has_user = bool(self.config.proxy_username)
            has_pass = bool(self.config.proxy_password)
            if has_user and has_pass:
                import aiohttp

                proxy_auth = aiohttp.BasicAuth(
                    login=self.config.proxy_username,
                    password=self.config.proxy_password,
                )
            elif has_user != has_pass:
                logger.warning(
                    "Discord proxy auth incomplete: both proxy_username and "
                    "proxy_password must be set; ignoring partial credentials",
                )

            self._client = DiscordBotClient(
                self,
                intents=intents,
                proxy=self.config.proxy,
                proxy_auth=proxy_auth,
            )
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
            raise
        finally:
            if not is_progress:
                await self._stop_typing(msg.chat_id)
                await self._clear_reactions(msg.chat_id)

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Progressive Discord delivery: send once, then edit until the stream ends."""
        client = self._client
        if client is None or not client.is_ready():
            logger.warning("Discord client not ready; dropping stream delta")
            return

        meta = metadata or {}
        stream_id = meta.get("_stream_id")

        if meta.get("_stream_end"):
            buf = self._stream_bufs.get(chat_id)
            if not buf or buf.message is None or not buf.text:
                return
            if stream_id is not None and buf.stream_id is not None and buf.stream_id != stream_id:
                return
            await self._finalize_stream(chat_id, buf)
            return

        buf = self._stream_bufs.get(chat_id)
        if buf is None or (
            stream_id is not None and buf.stream_id is not None and buf.stream_id != stream_id
        ):
            buf = _StreamBuf(stream_id=stream_id)
            self._stream_bufs[chat_id] = buf
        elif buf.stream_id is None:
            buf.stream_id = stream_id

        buf.text += delta
        if not buf.text.strip():
            return

        target = await self._resolve_channel(chat_id)
        if target is None:
            logger.warning("Discord stream target {} unavailable", chat_id)
            return

        now = time.monotonic()
        if buf.message is None:
            try:
                buf.message = await target.send(content=buf.text)
                buf.last_edit = now
            except Exception as e:
                logger.warning("Discord stream initial send failed: {}", e)
                raise
            return

        if (now - buf.last_edit) < self._STREAM_EDIT_INTERVAL:
            return

        try:
            await buf.message.edit(content=DiscordBotClient._build_chunks(buf.text, [], False)[0])
            buf.last_edit = now
        except Exception as e:
            logger.warning("Discord stream edit failed: {}", e)
            raise

    async def _handle_discord_message(self, message: discord.Message) -> None:
        """Handle incoming Discord messages from discord.py.

        Self-loop guard: only drop messages from this bot's own account. Messages
        from other bots are allowed through so multi-agent setups (one bot asking
        another for help, a bot mentioning another by @name, etc.) can work.
        Bot-from-bot loops are still prevented per-instance because each bot
        still ignores its own outbound messages. (#3217)
        """
        if self._bot_user_id is not None and str(message.author.id) == self._bot_user_id:
            return
        if self._is_system_message(message):
            return

        sender_id = str(message.author.id)
        channel_id = self._channel_key(message.channel)
        self._remember_channel(message.channel)
        content = message.content or ""

        if not self._should_accept_inbound(message, sender_id, content):
            return

        media_paths, attachment_markers = await self._download_attachments(message.attachments)
        full_content = self._compose_inbound_content(content, attachment_markers)
        metadata = self._build_inbound_metadata(message)
        parent_channel_id = self._channel_parent_key(message.channel)
        session_key = None
        if parent_channel_id is not None:
            metadata["parent_channel_id"] = parent_channel_id
            metadata["context_chat_id"] = parent_channel_id
            metadata["thread_id"] = channel_id
            session_key = f"{self.name}:{parent_channel_id}:thread:{channel_id}"

        await self._start_typing(message.channel)

        # Add read receipt reaction immediately, working emoji after delay
        try:
            await message.add_reaction(self.config.read_receipt_emoji)
            self._pending_reactions[channel_id] = message
        except Exception as e:
            logger.debug("Failed to add read receipt reaction: {}", e)

        # Delayed working indicator (cosmetic — not tied to subagent lifecycle)
        async def _delayed_working_emoji() -> None:
            await asyncio.sleep(self.config.working_emoji_delay)
            with suppress(Exception):
                await message.add_reaction(self.config.working_emoji)

        self._working_emoji_tasks[channel_id] = asyncio.create_task(_delayed_working_emoji())

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=channel_id,
                content=full_content,
                media=media_paths,
                metadata=metadata,
                session_key=session_key,
            )
        except Exception:
            await self._clear_reactions(channel_id)
            await self._stop_typing(channel_id)
            raise

    async def _on_message(self, message: discord.Message) -> None:
        """Backward-compatible alias for legacy tests/callers."""
        await self._handle_discord_message(message)

    async def _resolve_channel(self, chat_id: str) -> Any | None:
        """Resolve a Discord channel from cache first, then network fetch."""
        client = self._client
        if client is None or not client.is_ready():
            return None
        channel = self._known_channels.get(chat_id)
        if channel is not None:
            return channel
        channel_id = int(chat_id)
        channel = client.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await client.fetch_channel(channel_id)
        except Exception as e:
            logger.warning("Discord channel {} unavailable: {}", chat_id, e)
            return None

    async def _finalize_stream(self, chat_id: str, buf: _StreamBuf) -> None:
        """Commit the final streamed content and flush overflow chunks."""
        chunks = DiscordBotClient._build_chunks(buf.text, [], False)
        if not chunks:
            self._stream_bufs.pop(chat_id, None)
            return

        try:
            await buf.message.edit(content=chunks[0])
        except Exception as e:
            logger.warning("Discord final stream edit failed: {}", e)
            raise

        target = getattr(buf.message, "channel", None) or await self._resolve_channel(chat_id)
        if target is None:
            logger.warning("Discord stream follow-up target {} unavailable", chat_id)
            self._stream_bufs.pop(chat_id, None)
            return

        for extra_chunk in chunks[1:]:
            await target.send(content=extra_chunk)

        self._stream_bufs.pop(chat_id, None)
        await self._stop_typing(chat_id)
        await self._clear_reactions(chat_id)

    def _should_accept_inbound(
        self,
        message: discord.Message,
        sender_id: str,
        content: str,
    ) -> bool:
        """Check if inbound Discord message should be processed."""
        if not self.is_allowed(sender_id):
            return False
        # Channel-based filtering: only respond in allowed channels
        allow_channels = self.config.allow_channels
        if allow_channels:
            channel_ids = self._channel_allow_keys(message.channel)
            if channel_ids.isdisjoint(allow_channels):
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
    def _is_system_message(message: discord.Message) -> bool:
        """Return True for Discord system messages that carry no user prompt."""
        message_type = getattr(message, "type", discord.MessageType.default)
        return message_type not in {discord.MessageType.default, discord.MessageType.reply}

    @staticmethod
    def _build_inbound_metadata(message: discord.Message) -> dict[str, str | None]:
        """Build metadata for inbound Discord messages."""
        reply_to = (
            str(message.reference.message_id)
            if message.reference and message.reference.message_id
            else None
        )
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
            if bot_user_id is None and self._client and self._client.user:
                bot_user_id = str(self._client.user.id)
            if bot_user_id is None:
                logger.debug(
                    "Discord message in {} ignored (bot identity unavailable)", message.channel.id
                )
                return False

            if any(str(user.id) == bot_user_id for user in message.mentions):
                return True
            if bot_user_id in {str(user_id) for user_id in getattr(message, "raw_mentions", [])}:
                return True
            if f"<@{bot_user_id}>" in content or f"<@!{bot_user_id}>" in content:
                return True
            if self._references_bot_message(message, bot_user_id):
                return True

            logger.debug("Discord message in {} ignored (bot not mentioned)", message.channel.id)
            return False

        return True

    @staticmethod
    def _references_bot_message(message: discord.Message, bot_user_id: str) -> bool:
        """Return True when a Discord reply targets a message authored by this bot."""
        reference = getattr(message, "reference", None)
        if reference is None:
            return False
        referenced_message = getattr(reference, "resolved", None) or getattr(
            reference, "cached_message", None
        )
        author = getattr(referenced_message, "author", None)
        return str(getattr(author, "id", "")) == bot_user_id

    async def _start_typing(self, channel: Messageable) -> None:
        """Start periodic typing indicator for a channel."""
        channel_id = self._channel_key(channel)
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            while self._running:
                try:
                    async with channel.typing():
                        await asyncio.sleep(TYPING_INTERVAL_S)
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.debug("Discord typing indicator failed for {}: {}", channel_id, e)
                    return

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator for a channel."""
        task = self._typing_tasks.pop(self._channel_key(channel_id), None)
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _clear_reactions(self, chat_id: str) -> None:
        """Remove all pending reactions after bot replies."""
        # Cancel delayed working emoji if it hasn't fired yet
        task = self._working_emoji_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

        msg_obj = self._pending_reactions.pop(chat_id, None)
        if msg_obj is None:
            return
        bot_user = self._client.user if self._client else None
        for emoji in (self.config.read_receipt_emoji, self.config.working_emoji):
            with suppress(Exception):
                await msg_obj.remove_reaction(emoji, bot_user)

    async def _cancel_all_typing(self) -> None:
        """Stop all typing tasks."""
        channel_ids = list(self._typing_tasks)
        for channel_id in channel_ids:
            await self._stop_typing(channel_id)

    async def _reset_runtime_state(self, close_client: bool) -> None:
        """Reset client and typing state."""
        await self._cancel_all_typing()
        self._stream_bufs.clear()
        self._known_channels.clear()
        if close_client and self._client is not None and not self._client.is_closed():
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("Discord client close failed: {}", e)
        self._client = None
        self._bot_user_id = None
