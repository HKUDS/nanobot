"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
import dataclasses
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Config

_INFLECTION_URL = "https://api.inflection.ai/external/api/inference"
_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_TTS_WORKSPACE = Path.home() / ".nanobot" / "workspace"
_TTS_MAX_CHARS = 4000  # ElevenLabs soft limit per request


async def _elevenlabs_tts(text: str, api_key: str, voice_id: str, chat_id: str = "") -> Path | None:
    """Generate voice audio from text using ElevenLabs TTS. Returns file path or None on error."""
    if not text or not api_key or not voice_id:
        return None

    # Strip markdown formatting and truncate for TTS
    import re
    clean = re.sub(r"```[\s\S]*?```", "", text)           # remove code blocks
    clean = re.sub(r"`[^`]+`", "", clean)                  # remove inline code
    clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)  # links → text
    clean = re.sub(r"[#*_~>]", "", clean).strip()          # strip markdown symbols
    if not clean:
        return None
    if len(clean) > _TTS_MAX_CHARS:
        clean = clean[:_TTS_MAX_CHARS] + "..."

    try:
        url = _ELEVENLABS_TTS_URL.format(voice_id=voice_id)
        # Save TTS to media/voicemessage/{receiverID}/
        if chat_id:
            tts_dir = Path.home() / ".nanobot" / "media" / "voicemessage" / str(chat_id)
        else:
            tts_dir = _TTS_WORKSPACE
        tts_dir.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": clean,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
                timeout=60.0,
            )
            resp.raise_for_status()

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = tts_dir / f"tts_{ts}.mp3"
        out_path.write_bytes(resp.content)

        # Tag with artist name
        try:
            import mutagen
            audio = mutagen.File(str(out_path), easy=True)
            if audio is not None:
                audio["artist"] = ["Mekkana Teknacryte"]
                audio.save()
        except Exception:
            pass

        return out_path

    except Exception as e:
        logger.warning("ElevenLabs TTS failed: {}", e)
        return None

_EQ_PROMPT = (
    "You are an emotionally intelligent conversational assistant. "
    "A user has sent a message to their personal AI, and the AI has drafted a response. "
    "Your job is to rewrite the response so it picks up on social cues — matching the "
    "emotional tone, energy level, and conversational style of the exchange. "
    "Make it feel warm, natural, and personal, like a thoughtful friend rather than a formal assistant. "
    "Preserve ALL factual content, answers, and information exactly — only adjust tone and social awareness. "
    "Do NOT add preamble or explanation — just return the rewritten response.\n\n"
    "Draft response to rewrite:\n{content}"
)


async def _inflection_eq(content: str, api_key: str) -> str:
    """Post-process a response through Inflection Pi-3.1 for social/emotional intelligence."""
    if not content or not api_key:
        return content
    # Skip pure code responses — no EQ rewrite needed
    stripped = content.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return content
    try:
        prompt = _EQ_PROMPT.format(content=content)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _INFLECTION_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"context": [{"text": prompt, "type": "Human"}], "config": "Pi-3.1"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if "text" in data:
                return data["text"]
            if "context" in data:
                for item in reversed(data["context"]):
                    if item.get("type") == "AI":
                        return item["text"]
    except Exception as e:
        logger.warning("Inflection EQ post-processing failed, using original: {}", e)
    return content


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages (with Inflection EQ post-processing on final responses)
    """

    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._inflection_api_key = os.environ.get("INFLECTION_API_KEY", "")
        self._elevenlabs_api_key = self.config.providers.elevenlabs.api_key or ""
        self._elevenlabs_voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "")

        self._init_channels()
    
    def _init_channels(self) -> None:
        """Initialize channels based on config."""
        
        # Telegram channel
        if self.config.channels.telegram.enabled:
            try:
                from nanobot.channels.telegram import TelegramChannel
                self.channels["telegram"] = TelegramChannel(
                    self.config.channels.telegram,
                    self.bus,
                    elevenlabs_api_key=self.config.providers.elevenlabs.api_key,
                )
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning("Telegram channel not available: {}", e)
        
        # WhatsApp channel
        if self.config.channels.whatsapp.enabled:
            try:
                from nanobot.channels.whatsapp import WhatsAppChannel
                self.channels["whatsapp"] = WhatsAppChannel(
                    self.config.channels.whatsapp, self.bus
                )
                logger.info("WhatsApp channel enabled")
            except ImportError as e:
                logger.warning("WhatsApp channel not available: {}", e)

        # Discord channel
        if self.config.channels.discord.enabled:
            try:
                from nanobot.channels.discord import DiscordChannel
                self.channels["discord"] = DiscordChannel(
                    self.config.channels.discord, self.bus
                )
                logger.info("Discord channel enabled")
            except ImportError as e:
                logger.warning("Discord channel not available: {}", e)
        
        # Feishu channel
        if self.config.channels.feishu.enabled:
            try:
                from nanobot.channels.feishu import FeishuChannel
                self.channels["feishu"] = FeishuChannel(
                    self.config.channels.feishu, self.bus
                )
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning("Feishu channel not available: {}", e)

        # Mochat channel
        if self.config.channels.mochat.enabled:
            try:
                from nanobot.channels.mochat import MochatChannel

                self.channels["mochat"] = MochatChannel(
                    self.config.channels.mochat, self.bus
                )
                logger.info("Mochat channel enabled")
            except ImportError as e:
                logger.warning("Mochat channel not available: {}", e)

        # DingTalk channel
        if self.config.channels.dingtalk.enabled:
            try:
                from nanobot.channels.dingtalk import DingTalkChannel
                self.channels["dingtalk"] = DingTalkChannel(
                    self.config.channels.dingtalk, self.bus
                )
                logger.info("DingTalk channel enabled")
            except ImportError as e:
                logger.warning("DingTalk channel not available: {}", e)

        # Email channel
        if self.config.channels.email.enabled:
            try:
                from nanobot.channels.email import EmailChannel
                self.channels["email"] = EmailChannel(
                    self.config.channels.email, self.bus
                )
                logger.info("Email channel enabled")
            except ImportError as e:
                logger.warning("Email channel not available: {}", e)

        # Slack channel
        if self.config.channels.slack.enabled:
            try:
                from nanobot.channels.slack import SlackChannel
                self.channels["slack"] = SlackChannel(
                    self.config.channels.slack, self.bus
                )
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
        
        # Matrix channel
        if self.config.channels.matrix.enabled:
            try:
                from nanobot.channels.matrix import MatrixChannel
                self.channels["matrix"] = MatrixChannel(
                    self.config.channels.matrix,
                    self.bus,
                )
                logger.info("Matrix channel enabled")
            except ImportError as e:
                logger.warning("Matrix channel not available: {}", e)
    
    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """Start a channel and log any exceptions."""
        try:
            await channel.start()
        except Exception as e:
            logger.error("Failed to start channel {}: {}", name, e)

    async def start_all(self) -> None:
        """Start all channels and the outbound dispatcher."""
        if not self.channels:
            logger.warning("No channels enabled")
            return
        
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
            except Exception as e:
                logger.error("Error stopping {}: {}", name, e)
    
    async def _dispatch_outbound(self) -> None:
        """Dispatch outbound messages to the appropriate channel."""
        logger.info("Outbound dispatcher started")
        
        while True:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )
                
                if msg.metadata.get("_progress"):
                    if msg.metadata.get("_tool_hint") and not self.config.channels.send_tool_hints:
                        continue
                    if not msg.metadata.get("_tool_hint") and not self.config.channels.send_progress:
                        continue
                else:
                    # Final response — apply Inflection EQ to pick up on social cues
                    if msg.content and self._inflection_api_key:
                        msg = dataclasses.replace(
                            msg,
                            content=await _inflection_eq(msg.content, self._inflection_api_key),
                        )

                    # ElevenLabs TTS — generate voice for every final response
                    if msg.content and self._elevenlabs_api_key and self._elevenlabs_voice_id:
                        voice_path = await _elevenlabs_tts(
                            msg.content, self._elevenlabs_api_key, self._elevenlabs_voice_id,
                            chat_id=msg.chat_id,
                        )
                        if voice_path:
                            existing_media = list(msg.media or [])
                            msg = dataclasses.replace(
                                msg,
                                media=existing_media + [str(voice_path)],
                            )

                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        await channel.send(msg)
                    except Exception as e:
                        logger.error("Error sending to {}: {}", msg.channel, e)
                else:
                    logger.warning("Unknown channel: {}", msg.channel)
                    
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
