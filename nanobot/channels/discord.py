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
from nanobot.channels.discord_ui import McpView, ModelPickerView, StatusView
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.providers.registry import PROVIDERS
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
    slash_commands_enabled: bool = True
    threads_per_conversation: bool = False  # used in Phase 4: thread-per-conversation feature
    ephemeral_commands: bool = True
    admin_role_ids: list[str] = Field(default_factory=list)
    # used in Phase 3: Path B admin commands. Empty = open access to all users.
    application_id: str = ""    # reserved for Phase 3 introspection
    guild_ids: list[str] = Field(default_factory=list)


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
        self._tree: discord.app_commands.CommandTree | None = None
        self._pending_interactions: dict[str, discord.Interaction] = {}
        self._attach_stop_button: set[str] = set()
        self._thread_map: dict[str, str] = {}  # original channel_id -> thread_id

    async def start(self) -> None:
        """Start the Discord client."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        intents = discord.Intents._from_value(self.config.intents)
        self._client = discord.Client(intents=intents)
        self._tree = discord.app_commands.CommandTree(self._client)

        if self.config.slash_commands_enabled:
            @self._tree.command(name="stop", description="Stop the current agent task")
            async def slash_stop(interaction: discord.Interaction) -> None:
                await self._inject_slash_as_message(interaction, "/stop")

            @self._tree.command(name="restart", description="Restart the agent")
            async def slash_restart(interaction: discord.Interaction) -> None:
                await self._inject_slash_as_message(interaction, "/restart")

            @self._tree.command(name="new", description="Start a new conversation")
            async def slash_new(interaction: discord.Interaction) -> None:
                await self._inject_slash_as_message(interaction, "/new")

            @self._tree.command(name="status", description="Show agent status")
            async def slash_status(interaction: discord.Interaction) -> None:
                await self._inject_slash_as_message(interaction, "/status")

            @self._tree.command(name="help", description="Show available commands")
            async def slash_help(interaction: discord.Interaction) -> None:
                embed = discord.Embed(title="nanobot Commands", color=discord.Color.blurple())
                embed.add_field(name="/stop", value="Stop the current agent task", inline=False)
                embed.add_field(name="/restart", value="Restart the bot process", inline=False)
                embed.add_field(name="/new", value="Start a new conversation session", inline=False)
                embed.add_field(name="/status", value="Show bot status", inline=False)
                embed.add_field(name="/model [model]", value="View or change the LLM model", inline=False)
                embed.add_field(name="/config", value="View Discord channel configuration (admin)", inline=False)
                embed.add_field(name="/mcp", value="List registered MCP servers (admin)", inline=False)
                await interaction.response.send_message(embed=embed, ephemeral=self.config.ephemeral_commands)

            @self._tree.command(name="model", description="View or change the LLM model")
            @discord.app_commands.describe(model="Model name (e.g. claude-opus-4-6)")
            async def slash_model(interaction: discord.Interaction, model: str | None = None) -> None:
                if model:
                    await self._inject_slash_as_message(interaction, f"/model {model}")
                    return
                providers = [(spec.name, spec.label) for spec in PROVIDERS][:20]

                async def on_model_confirm(provider: str, model_name: str) -> None:
                    from nanobot.bus.events import InboundMessage  # noqa: PLC0415
                    await self.bus.publish_inbound(InboundMessage(
                        channel=self.name,
                        sender_id="__model_picker__",
                        chat_id=str(interaction.channel_id),
                        content=f"/model {provider}/{model_name}",
                        metadata={"message_id": "", "guild_id": str(interaction.guild_id) if interaction.guild_id else None, "reply_to": None},
                    ))

                view = ModelPickerView(providers=providers, on_confirm=on_model_confirm)
                embed = discord.Embed(
                    title="Model Picker",
                    description="Select a provider then click **Set Model** to enter a model name.",
                    color=discord.Color.blurple(),
                )
                await interaction.response.send_message(
                    embed=embed, view=view, ephemeral=self.config.ephemeral_commands
                )

            @slash_model.autocomplete("model")
            async def model_autocomplete(
                interaction: discord.Interaction, current: str
            ) -> list[discord.app_commands.Choice[str]]:
                suggestions = [
                    "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5",
                    "gpt-4o", "gpt-4o-mini",
                    "gemini-2.5-pro", "gemini-2.0-flash",
                    "deepseek-chat", "deepseek-reasoner",
                ]
                filtered = [s for s in suggestions if current.lower() in s.lower()][:25]
                return [discord.app_commands.Choice(name=s, value=s) for s in filtered]

            @self._tree.command(name="config", description="View Discord channel configuration")
            async def slash_config(interaction: discord.Interaction) -> None:
                # admin_role_ids guard: empty list = open access. In DMs, user has no roles, so DM users
                # always pass when admin_role_ids is non-empty (user.roles is []).
                if self.config.admin_role_ids:
                    member_roles = [
                        str(r.id)
                        for r in (interaction.user.roles if hasattr(interaction.user, "roles") else [])
                    ]
                    if not any(r in member_roles for r in self.config.admin_role_ids):
                        await interaction.response.send_message("Admin access required.", ephemeral=True)
                        return
                embed = discord.Embed(title="Discord Channel Config", color=discord.Color.blue())
                embed.add_field(name="group_policy", value=self.config.group_policy, inline=True)
                embed.add_field(name="slash_commands_enabled", value=str(self.config.slash_commands_enabled), inline=True)
                embed.add_field(name="ephemeral_commands", value=str(self.config.ephemeral_commands), inline=True)
                embed.add_field(name="threads_per_conversation", value=str(self.config.threads_per_conversation), inline=True)
                embed.add_field(name="guild_ids", value=", ".join(self.config.guild_ids) or "(global)", inline=True)
                embed.add_field(name="admin_role_ids", value=", ".join(self.config.admin_role_ids) or "(none)", inline=True)
                await interaction.response.send_message(embed=embed, ephemeral=self.config.ephemeral_commands)

            @self._tree.command(name="mcp", description="List registered MCP servers")
            async def slash_mcp(interaction: discord.Interaction) -> None:
                # admin_role_ids guard: empty list = open access. In DMs, user has no roles, so DM users
                # always pass when admin_role_ids is non-empty (user.roles is []).
                if self.config.admin_role_ids:
                    member_roles = [
                        str(r.id)
                        for r in (interaction.user.roles if hasattr(interaction.user, "roles") else [])
                    ]
                    if not any(r in member_roles for r in self.config.admin_role_ids):
                        await interaction.response.send_message("Admin access required.", ephemeral=True)
                        return
                mcp_servers: list[str] = []
                try:
                    from nanobot.config.loader import load_config  # noqa: PLC0415
                    cfg = load_config()
                    if hasattr(cfg, "mcp") and cfg.mcp:
                        mcp_servers = list(cfg.mcp.keys())
                except Exception:
                    pass
                view = McpView(mcp_servers)
                embed = discord.Embed(title="MCP Servers", color=discord.Color.green())
                if mcp_servers:
                    for name in mcp_servers:
                        embed.add_field(name=name, value="registered", inline=True)
                else:
                    embed.description = "No MCP servers configured."
                await interaction.response.send_message(embed=embed, view=view, ephemeral=self.config.ephemeral_commands)

        @self._client.event
        async def on_ready() -> None:
            self._bot_user_id = str(self._client.user.id)
            logger.info("Discord ready as {}", self._client.user)
            if self.config.slash_commands_enabled:
                if self.config.guild_ids:
                    for gid in self.config.guild_ids:
                        guild_obj = discord.Object(id=int(gid))
                        self._tree.copy_global_to(guild=guild_obj)
                        await self._tree.sync(guild=guild_obj)
                    logger.info("Discord slash commands synced to {} guilds", len(self.config.guild_ids))
                else:
                    await self._tree.sync()
                    logger.warning("Discord slash commands synced globally (up to 1hr propagation delay)")

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
        self._pending_interactions.clear()
        self._attach_stop_button.clear()
        self._thread_map.clear()
        if self._client:
            await self._client.close()
            self._client = None
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message via discord.py, including file attachments."""
        attach_stop = msg.chat_id in self._attach_stop_button
        self._attach_stop_button.discard(msg.chat_id)
        interaction = self._pending_interactions.pop(msg.chat_id, None)

        if not self._client:
            logger.warning("Discord client not initialized")
            return

        if interaction is None:
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
                    if interaction is not None:
                        await interaction.followup.send(file=discord.File(path))
                    else:
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
                if interaction is not None:
                    await interaction.followup.send(content="✓", ephemeral=self.config.ephemeral_commands)
                return

            for i, chunk in enumerate(chunks):
                try:
                    if interaction is not None:
                        await interaction.followup.send(content=chunk)
                    else:
                        reference = None
                        if i == 0 and msg.reply_to and not sent_media:
                            reference = discord.MessageReference(
                                message_id=int(msg.reply_to),
                                channel_id=int(msg.chat_id),
                                fail_if_not_exists=False,
                            )
                        view: discord.ui.View | None = None
                        if i == 0 and attach_stop:
                            chat_id_capture = msg.chat_id

                            async def _stop_cb() -> None:
                                from nanobot.bus.events import InboundMessage  # noqa: PLC0415
                                # sender_id is a sentinel — stop is a priority command processed before is_allowed()
                                # in AgentLoop.run(), so no real user ID is needed here.
                                await self.bus.publish_inbound(InboundMessage(
                                    channel=self.name,
                                    sender_id="__stop_button__",
                                    chat_id=chat_id_capture,
                                    content="/stop",
                                    metadata={"message_id": "", "guild_id": None, "reply_to": None},
                                ))

                            view = StatusView(on_stop=_stop_cb)
                        await channel.send(
                            content=chunk,
                            reference=reference,
                            mention_author=False,
                            view=view,
                        )
                except Exception as e:
                    logger.error("Error sending Discord message: {}", e)
                    break  # Abort remaining chunks on failure
        finally:
            await self._stop_typing(msg.chat_id)

    async def _inject_slash_as_message(
        self,
        interaction: discord.Interaction,
        text: str,
    ) -> None:
        """Defer interaction and inject text as InboundMessage to bus."""
        if not self.is_allowed(str(interaction.user.id)):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return
        channel_id = str(interaction.channel_id)
        await interaction.response.defer(thinking=True, ephemeral=self.config.ephemeral_commands)
        self._pending_interactions[channel_id] = interaction
        # TODO: Phase 3 — if two slash commands fire before the first is answered, the second
        # overwrites _pending_interactions[channel_id] and the first deferred interaction
        # will never get a followup (Discord marks it failed). Consider per-channel locking.
        await self._handle_message(
            sender_id=str(interaction.user.id),
            chat_id=channel_id,
            content=text,
            metadata={
                "message_id": "",
                "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                "reply_to": None,
            },
        )

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

        # Thread-per-conversation: create a thread for each new conversation in a text channel
        thread_id: str | None = None
        if self.config.threads_per_conversation and guild_id is not None:
            # Don't create a thread if we're already in one (message.channel is a Thread)
            if not isinstance(message.channel, discord.Thread):
                # Reuse existing thread for this channel if we have one
                if channel_id in self._thread_map:
                    thread_id = self._thread_map[channel_id]
                else:
                    try:
                        thread = await message.create_thread(
                            name=f"Chat with {message.author.display_name}"[:100]
                        )
                        thread_id = str(thread.id)
                        self._thread_map[channel_id] = thread_id
                        logger.info("Discord: created thread {} for channel {}", thread_id, channel_id)
                    except Exception as e:
                        logger.warning("Discord: failed to create thread: {}", e)

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

        effective_chat_id = thread_id if thread_id else channel_id
        session_key = f"discord:{effective_chat_id}" if thread_id else None

        typing_target = message.channel
        if thread_id:
            thread_channel = self._client.get_channel(int(thread_id)) if self._client else None
            if thread_channel:
                typing_target = thread_channel
        await self._start_typing(typing_target)

        self._attach_stop_button.add(effective_chat_id)
        await self._handle_message(
            sender_id=sender_id,
            chat_id=effective_chat_id,
            content="\n".join(p for p in content_parts if p) or "[empty message]",
            media=media_paths,
            metadata={
                "message_id": str(message.id),
                "guild_id": guild_id,
                "reply_to": reply_to,
            },
            session_key=session_key,
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
