"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Config


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
        self._dead_letter_file = self.config.workspace_path / "outbound_failed.jsonl"

        self._init_channels()

    def _write_dead_letter(self, msg: OutboundMessage, error: Exception | None) -> None:
        """Persist undelivered outbound messages for manual replay/debugging."""
        try:
            path: Path = self._dead_letter_file
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "timestamp": datetime.now().isoformat(),
                "channel": msg.channel,
                "chat_id": msg.chat_id,
                "content": msg.content,
                "media": list(msg.media or []),
                "metadata": dict(msg.metadata or {}),
                "error": str(error) if error else "unknown delivery error",
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error("Failed writing outbound dead letter: {}", e)

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
                )
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning("Telegram channel not available: {}", e)

        # WhatsApp channel
        if self.config.channels.whatsapp.enabled:
            try:
                from nanobot.channels.whatsapp import WhatsAppChannel

                self.channels["whatsapp"] = WhatsAppChannel(self.config.channels.whatsapp, self.bus)
                logger.info("WhatsApp channel enabled")
            except ImportError as e:
                logger.warning("WhatsApp channel not available: {}", e)

        # Discord channel
        if self.config.channels.discord.enabled:
            try:
                from nanobot.channels.discord import DiscordChannel

                self.channels["discord"] = DiscordChannel(self.config.channels.discord, self.bus)
                logger.info("Discord channel enabled")
            except ImportError as e:
                logger.warning("Discord channel not available: {}", e)

        # Feishu channel
        if self.config.channels.feishu.enabled:
            try:
                from nanobot.channels.feishu import FeishuChannel

                self.channels["feishu"] = FeishuChannel(self.config.channels.feishu, self.bus)
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning("Feishu channel not available: {}", e)

        # Mochat channel
        if self.config.channels.mochat.enabled:
            try:
                from nanobot.channels.mochat import MochatChannel

                self.channels["mochat"] = MochatChannel(self.config.channels.mochat, self.bus)
                logger.info("Mochat channel enabled")
            except ImportError as e:
                logger.warning("Mochat channel not available: {}", e)

        # DingTalk channel
        if self.config.channels.dingtalk.enabled:
            try:
                from nanobot.channels.dingtalk import DingTalkChannel

                self.channels["dingtalk"] = DingTalkChannel(self.config.channels.dingtalk, self.bus)
                logger.info("DingTalk channel enabled")
            except ImportError as e:
                logger.warning("DingTalk channel not available: {}", e)

        # Email channel
        if self.config.channels.email.enabled:
            try:
                from nanobot.channels.email import EmailChannel

                self.channels["email"] = EmailChannel(self.config.channels.email, self.bus)
                logger.info("Email channel enabled")
            except ImportError as e:
                logger.warning("Email channel not available: {}", e)

        # Slack channel
        if self.config.channels.slack.enabled:
            try:
                from nanobot.channels.slack import SlackChannel

                self.channels["slack"] = SlackChannel(self.config.channels.slack, self.bus)
                logger.info("Slack channel enabled")
            except ImportError as e:
                logger.warning("Slack channel not available: {}", e)

        # QQ channel
        if self.config.channels.qq.enabled:
            try:
                from nanobot.channels.qq import QQChannel

                self.channels["qq"] = QQChannel(
                    self.config.channels.qq,
                    self.bus,
                )
                logger.info("QQ channel enabled")
            except ImportError as e:
                logger.warning("QQ channel not available: {}", e)

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:  # crash-barrier: channel startup varies
            logger.error("Failed to start channel {}: {}", name, e)

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return

        # Auto-replay dead letters on startup (Step 16)
        if self._dead_letter_file.exists():
            try:
                total, ok, fail = await self.replay_dead_letters()
                if total:
                    logger.info(
                        "Dead-letter replay: {} sent, {} still failed (of {})", ok, fail, total
                    )
            except Exception:  # crash-barrier: replay may hit varied channel errors
                logger.exception("Dead-letter auto-replay failed")

        # Start outbound dispatcher
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # Start channels
        tasks = []
        for name, channel in self.channels.items():
            logger.info("Starting {} channel...", name)
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))

        # Wait for all to complete (they should run forever)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """Stop all channels and the dispatcher."""
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
                logger.info("Stopped {} channel", name)
            except Exception as e:  # crash-barrier: channel stop varies
                logger.error("Error stopping {}: {}", name, e)

    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")

        while True:
            try:
                msg = await asyncio.wait_for(self.bus.consume_outbound(), timeout=1.0)

                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not self.config.channels.send_tool_hints:
                        continue
                    if (
                        not msg.metadata.get("_tool_hint")
                        and not self.config.channels.send_progress
                    ):
                        continue

                channel = self.channels.get(msg.channel)
                if channel:
                    last_error: Exception | None = None
                    sent = False
                    for attempt in range(1, 4):
                        try:
                            await channel.send(msg)
                            sent = True
                            break
                        except Exception as e:  # crash-barrier: channel send varies
                            last_error = e
                            logger.exception(
                                "Error sending to {} (attempt {}/3): {}", msg.channel, attempt, e
                            )
                            if attempt < 3:
                                await asyncio.sleep(0.5 * attempt)
                    if not sent:
                        self._write_dead_letter(msg, last_error)
                        logger.error(
                            "Outbound message persisted to {} after delivery failure",
                            self._dead_letter_file,
                        )
                else:
                    logger.warning("Unknown channel: {}", msg.channel)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:  # crash-barrier: keep dispatcher alive
                # Keep dispatcher alive even on unexpected errors.
                logger.exception("Outbound dispatcher error: {}", e)
                continue

    def get_channel(self, name: str) -> BaseChannel | None:
        """Get a channel by name."""
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """Get status of all channels."""
        return {
            name: {"enabled": True, "running": channel.is_running}
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        """Get list of enabled channel names."""
        return list(self.channels.keys())

    # ------------------------------------------------------------------
    # Dead-letter replay (Step 16)
    # ------------------------------------------------------------------

    def _read_dead_letters(self) -> list[dict[str, Any]]:
        """Read all entries from the dead-letter file."""
        path = self._dead_letter_file
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items

    async def replay_dead_letters(self, *, dry_run: bool = False) -> tuple[int, int, int]:
        """Replay undelivered outbound messages.

        Returns ``(total, succeeded, failed)`` counts.
        """
        entries = self._read_dead_letters()
        if not entries:
            return (0, 0, 0)

        succeeded = 0
        failed_entries: list[dict[str, Any]] = []

        for entry in entries:
            channel_name = entry.get("channel", "")
            channel = self.channels.get(channel_name)
            if channel is None:
                logger.warning("Replay skip: channel '{}' not available", channel_name)
                failed_entries.append(entry)
                continue

            msg = OutboundMessage(
                channel=channel_name,
                chat_id=entry.get("chat_id", ""),
                content=entry.get("content", ""),
                media=entry.get("media", []),
                metadata=entry.get("metadata", {}),
            )

            if dry_run:
                logger.info(
                    "Dry-run replay → {}:{} ({} chars)", channel_name, msg.chat_id, len(msg.content)
                )
                succeeded += 1
                continue

            try:
                await channel.send(msg)
                succeeded += 1
                logger.info("Replayed message to {}:{}", channel_name, msg.chat_id)
            except Exception as exc:  # crash-barrier: channel send varies
                logger.error("Replay failed for {}:{}: {}", channel_name, msg.chat_id, exc)
                failed_entries.append(entry)

        # Rewrite the dead-letter file with only the still-failed entries
        if not dry_run:
            if failed_entries:
                with open(self._dead_letter_file, "w", encoding="utf-8") as f:
                    for e in failed_entries:
                        f.write(json.dumps(e, ensure_ascii=False) + "\n")
            elif self._dead_letter_file.exists():
                self._dead_letter_file.unlink()

        total = len(entries)
        return (total, succeeded, total - succeeded)
