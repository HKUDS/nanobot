"""Discord channel implementation using discord.py."""


from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DiscordConfig


class DiscordChannel(BaseChannel):
    """
    Discord channel using discord.py.

    Connects to Discord Gateway API for real-time message handling.
    """

    name = "discord"

    def __init__(self, config: DiscordConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self._client: any = None
        self._running = False

    async def start(self) -> None:
        """Start the Discord bot."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        try:
            import discord
        except ImportError:
            logger.error("discord.py not installed. Install with: pip install discord.py")
            return

        # Define intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True

        # Create client
        self._client = discord.Client(intents=intents)

        # Register event handlers
        @self._client.event
        async def on_ready():
            logger.info(f"Discord bot {self._client.user} connected")

        @self._client.event
        async def on_message(message: discord.Message):
            # Ignore messages from bots
            if message.author.bot:
                return

            # Get sender ID
            sender_id = str(message.author.id)

            # Use channel ID as chat_id for DMs, or thread/channel ID for guilds
            if isinstance(message.channel, discord.DMChannel):
                chat_id = str(message.author.id)  # Use user ID for DMs
            else:
                chat_id = str(message.channel.id)  # Use channel ID for servers

            # Build content
            content_parts = []
            media_paths = []

            # Text content
            if message.content:
                content_parts.append(message.content)

            # Handle attachments
            for attachment in message.attachments:
                try:
                    # Download attachment to workspace/media/
                    from pathlib import Path

                    media_dir = Path.home() / ".nanobot" / "media"
                    media_dir.mkdir(parents=True, exist_ok=True)

                    # Determine file extension
                    ext = Path(attachment.filename).suffix
                    file_path = media_dir / f"{attachment.id}{ext}"

                    # Download file
                    await attachment.save(str(file_path))
                    media_paths.append(str(file_path))

                    # Add content reference
                    content_parts.append(f"[attachment: {attachment.filename} → {file_path}]")

                    logger.debug(f"Downloaded attachment to {file_path}")
                except Exception as e:
                    logger.error(f"Failed to download attachment: {e}")
                    content_parts.append(f"[attachment: {attachment.filename} - download failed]")

            content = "\n".join(content_parts) if content_parts else "[empty message]"

            logger.debug(f"Discord message from {sender_id}: {content[:50]}...")

            # Forward to the message bus
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message.id,
                    "username": str(message.author),
                    "display_name": message.author.display_name,
                    "is_dm": isinstance(message.channel, discord.DMChannel),
                    "guild_id": message.guild.id if message.guild else None,
                    "guild_name": message.guild.name if message.guild else None,
                },
            )

        self._running = True
        logger.info("Starting Discord bot...")

        try:
            await self._client.start(self.config.token)
        except Exception as e:
            logger.error(f"Discord bot error: {e}")
            self._running = False

    async def stop(self) -> None:
        """Stop the Discord bot."""
        self._running = False

        if self._client:
            logger.info("Stopping Discord bot...")
            await self._client.close()
            self._client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord."""
        if not self._client:
            logger.warning("Discord client not running")
            return

        try:
            import discord

            # Parse chat_id to get target
            # For DMs, chat_id is the user ID
            # For servers, chat_id is the channel ID
            target_id = int(msg.chat_id)

            # Try to get channel or user
            try:
                # Try as a channel first (for server channels or DM channels)
                channel = self._client.get_channel(target_id)

                if channel is None:
                    # If not found, try to get user and create DM
                    user = self._client.get_user(target_id)
                    if user:
                        channel = await user.create_dm()

                if channel:
                    # Discord has a 2000 character limit for messages
                    content = msg.content
                    if len(content) > 2000:
                        # Split long messages
                        parts = [content[i : i + 2000] for i in range(0, len(content), 2000)]
                        for part in parts:
                            await channel.send(part)
                    else:
                        await channel.send(content)
                    logger.debug(f"Sent Discord message to {target_id}")
                else:
                    logger.warning(f"Could not find channel or user: {target_id}")

            except discord.NotFound:
                logger.error(f"Discord channel/user not found: {target_id}")
            except discord.Forbidden:
                logger.error(f"No permission to send to Discord channel/user: {target_id}")
            except Exception as e:
                logger.error(f"Error sending Discord message: {e}")

        except Exception as e:
            logger.error(f"Unexpected error sending Discord message: {e}")
