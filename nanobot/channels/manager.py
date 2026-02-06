"""Channel manager for coordinating chat channels."""

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Config
from nanobot.providers.tts import TTSProvider


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages
    """

    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._tts_provider: TTSProvider | None = None

        # Initialize cleanup registry
        from nanobot.utils.media_cleanup import MediaCleanupRegistry
        media_dir = Path.home() / ".nanobot" / "media"
        self._cleanup_registry = MediaCleanupRegistry(media_dir)

        self._init_tts_provider()
        self._init_channels()

    def _init_tts_provider(self) -> None:
        """Initialize TTS provider if enabled."""
        if self.config.tools.multimodal.tts.enabled:
            from nanobot.providers.tts import TTSProvider

            # Use TTS-specific API key if provided, otherwise fall back to provider key
            provider = self.config.tools.multimodal.tts.provider
            api_key = self.config.tools.multimodal.tts.api_key

            # Provider-specific fallback logic
            if not api_key:
                if provider == "openai":
                    api_key = self.config.providers.openai.api_key
                else:
                    logger.warning(f"TTS provider '{provider}' requires explicit API key")
                    return

            if not api_key:
                logger.warning("TTS enabled but no API key configured")
                return

            self._tts_provider = TTSProvider(
                provider=provider,
                api_key=api_key,
                voice=self.config.tools.multimodal.tts.voice,
                model=self.config.tools.multimodal.tts.model,
                max_text_length=self.config.tools.multimodal.tts.max_text_length,
                timeout=self.config.tools.multimodal.tts.timeout,
            )
            logger.info(
                f"TTS provider initialized: {self._tts_provider.provider} "
                f"(model={self._tts_provider.model}, "
                f"voice={self._tts_provider.voice}, "
                f"max_length={self._tts_provider.max_text_length})"
            )

    def _init_channels(self) -> None:
        """Initialize channels based on config."""

        # Telegram channel
        if self.config.channels.telegram.enabled:
            try:
                from nanobot.channels.telegram import TelegramChannel
                self.channels["telegram"] = TelegramChannel(
                    self.config.channels.telegram,
                    self.bus,
                    groq_api_key=self.config.providers.groq.api_key,
                    tts_provider=self._tts_provider,
                    max_video_frames=self.config.tools.multimodal.max_video_frames,
                    video_frame_interval=self.config.tools.multimodal.video_frame_interval,
                    video_max_frame_width=self.config.tools.multimodal.video_max_frame_width,
                    workspace=self.config.workspace_path,
                    cleanup_registry=self._cleanup_registry,
                )
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning(f"Telegram channel not available: {e}")

        # WhatsApp channel
        if self.config.channels.whatsapp.enabled:
            try:
                from nanobot.channels.whatsapp import WhatsAppChannel
                self.channels["whatsapp"] = WhatsAppChannel(
                    self.config.channels.whatsapp, self.bus
                )
                logger.info("WhatsApp channel enabled")
            except ImportError as e:
                logger.warning(f"WhatsApp channel not available: {e}")

        # Discord channel
        if self.config.channels.discord.enabled:
            try:
                from nanobot.channels.discord import DiscordChannel
                self.channels["discord"] = DiscordChannel(
                    self.config.channels.discord, self.bus
                )
                logger.info("Discord channel enabled")
            except ImportError as e:
                logger.warning(f"Discord channel not available: {e}")

        # Feishu channel
        if self.config.channels.feishu.enabled:
            try:
                from nanobot.channels.feishu import FeishuChannel
                self.channels["feishu"] = FeishuChannel(
                    self.config.channels.feishu, self.bus
                )
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning(f"Feishu channel not available: {e}")

    async def start_all(self) -> None:
        """Start WhatsApp channel and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return

        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # Start WhatsApp channel
        tasks = []
        for name, channel in self.channels.items():
            logger.info(f"Starting {name} channel...")
            tasks.append(asyncio.create_task(channel.start()))

        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all channels, the dispatcher, and cleanup services."""
        logger.info("Stopping all channels...")

        # Stop dispatcher
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass

        # Stop all channels
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info(f"Stopped {name} channel")
            except Exception as e:
                logger.error(f"Error stopping {name}: {e}")

        # Stop media cleanup registry and clean up files
        if self._cleanup_registry:
            try:
                cleaned = self._cleanup_registry.cleanup_now()
                logger.info(f"Cleaned up {cleaned} media files on shutdown")
            except Exception as e:
                logger.error(f"Error during media cleanup: {e}")

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )

                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error(f"Error sending to {msg.channel}: {e}")
                else:
                    logger.warning(f"Unknown channel: {msg.channel}")

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {
                "enabled": True,
                "running": channel.is_running
            }
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())
