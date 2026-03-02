"""Channel manager for coordinating chat channels."""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re as _re
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from scorpion.bus.events import OutboundMessage
from scorpion.bus.queue import MessageBus
from scorpion.channels.base import BaseChannel
from scorpion.config.schema import Config, TTS_MODEL

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_TTS_WORKSPACE = Path.home() / ".scorpion" / "workspace"
_TTS_MAX_CHARS = 4000  # ElevenLabs soft limit per request
_GEMINI_TTS_MAX_CHARS = 5000  # Gemini TTS limit


def _clean_for_tts(text: str) -> str:
    """Strip markdown formatting for TTS input."""
    clean = _re.sub(r"```[\s\S]*?```", "", text)           # code blocks
    clean = _re.sub(r"`[^`]+`", "", clean)                  # inline code
    clean = _re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)  # links → text
    clean = _re.sub(r"[#*_~>]", "", clean).strip()          # markdown symbols
    return clean


async def _elevenlabs_tts(text: str, api_key: str, voice_id: str, chat_id: str = "") -> Path | None:
    """Generate voice audio from text using ElevenLabs TTS. Returns file path or None on error."""
    if not text or not api_key or not voice_id:
        return None

    clean = _clean_for_tts(text)
    if not clean:
        return None
    if len(clean) > _TTS_MAX_CHARS:
        clean = clean[:_TTS_MAX_CHARS] + "..."

    try:
        url = _ELEVENLABS_TTS_URL.format(voice_id=voice_id)
        if chat_id:
            tts_dir = Path.home() / ".scorpion" / "media" / "voicemessage" / str(chat_id)
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


async def _gemini_tts(
    text: str, api_key: str, chat_id: str = "", voice: str = "Kore",
) -> Path | None:
    """Generate voice audio from text using Gemini TTS. Returns WAV file path or None."""
    if not text or not api_key:
        return None

    clean = _clean_for_tts(text)
    if not clean:
        return None
    if len(clean) > _GEMINI_TTS_MAX_CHARS:
        clean = clean[:_GEMINI_TTS_MAX_CHARS] + "..."

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model=TTS_MODEL,
            contents=f"Say naturally: {clean}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                    )
                ),
            ),
        )

        audio_data = None
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("audio/"):
                audio_data = part.inline_data.data
                break

        if not audio_data:
            logger.warning("Gemini TTS returned no audio")
            return None

        if chat_id:
            tts_dir = Path.home() / ".scorpion" / "media" / "voicemessage" / str(chat_id)
        else:
            tts_dir = _TTS_WORKSPACE
        tts_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = tts_dir / f"tts_{ts}.wav"

        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(24000)
            wf.writeframes(audio_data)

        logger.info("Gemini TTS generated: {} ({} bytes)", out_path, len(audio_data))
        return out_path

    except Exception as e:
        logger.warning("Gemini TTS failed: {}", e)
        return None


class ChannelManager:
    """
    Manages chat channels and coordinates message routing.

    Responsibilities:
    - Initialize enabled channels (Telegram, WhatsApp, etc.)
    - Start/stop channels
    - Route outbound messages (with optional auto-TTS)
    """

    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.channels: dict[str, BaseChannel] = {}
        self._dispatch_task: asyncio.Task | None = None
        self._elevenlabs_api_key = self.config.providers.elevenlabs.api_key or ""
        self._elevenlabs_voice_id = self.config.providers.elevenlabs.voice_id or ""
        self._gemini_api_key = self.config.providers.gemini.api_key or ""

        self._init_channels()

    def _init_channels(self) -> None:
        """Initialize channels based on config."""

        # Telegram channel
        if self.config.channels.telegram.enabled:
            try:
                from scorpion.channels.telegram import TelegramChannel
                self.channels["telegram"] = TelegramChannel(
                    self.config.channels.telegram,
                    self.bus,
                    elevenlabs_api_key=self.config.providers.elevenlabs.api_key,
                    gemini_api_key=self.config.providers.gemini.api_key,
                )
                logger.info("Telegram channel enabled")
            except ImportError as e:
                logger.warning("Telegram channel not available: {}", e)

        # Feishu channel
        if self.config.channels.feishu.enabled:
            try:
                from scorpion.channels.feishu import FeishuChannel
                self.channels["feishu"] = FeishuChannel(
                    self.config.channels.feishu, self.bus
                )
                logger.info("Feishu channel enabled")
            except ImportError as e:
                logger.warning("Feishu channel not available: {}", e)

        # Mochat channel
        if self.config.channels.mochat.enabled:
            try:
                from scorpion.channels.mochat import MochatChannel

                self.channels["mochat"] = MochatChannel(
                    self.config.channels.mochat, self.bus
                )
                logger.info("Mochat channel enabled")
            except ImportError as e:
                logger.warning("Mochat channel not available: {}", e)

        # Email channel
        if self.config.channels.email.enabled:
            try:
                from scorpion.channels.email import EmailChannel
                self.channels["email"] = EmailChannel(
                    self.config.channels.email, self.bus
                )
                logger.info("Email channel enabled")
            except ImportError as e:
                logger.warning("Email channel not available: {}", e)

        # Slack channel
        if self.config.channels.slack.enabled:
            try:
                from scorpion.channels.slack import SlackChannel
                self.channels["slack"] = SlackChannel(
                    self.config.channels.slack, self.bus
                )
                logger.info("Slack channel enabled")
            except ImportError as e:
                logger.warning("Slack channel not available: {}", e)

        # QQ channel
        if self.config.channels.qq.enabled:
            try:
                from scorpion.channels.qq import QQChannel
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
                    # Auto-TTS for voice replies (skip if audio already attached by generate_speech tool)
                    has_audio = any(
                        p.endswith((".wav", ".mp3", ".ogg", ".m4a"))
                        for p in (msg.media or [])
                    )
                    if msg.content and not has_audio:
                        voice_cfg = self._voice_config_for(msg.channel)
                        is_voice_reply = msg.metadata.get("voice_reply", False)
                        want_tts = False
                        if voice_cfg and voice_cfg.enabled and is_voice_reply:
                            want_tts = True
                        if voice_cfg and voice_cfg.always:
                            want_tts = True

                        if want_tts:
                            voice_path = None
                            voice_name = voice_cfg.voice if voice_cfg else "Kore"
                            # Prefer ElevenLabs if configured
                            if self._elevenlabs_api_key and self._elevenlabs_voice_id:
                                voice_path = await _elevenlabs_tts(
                                    msg.content, self._elevenlabs_api_key,
                                    self._elevenlabs_voice_id, chat_id=msg.chat_id,
                                )
                            # Fall back to Gemini TTS
                            if not voice_path and self._gemini_api_key:
                                voice_path = await _gemini_tts(
                                    msg.content, self._gemini_api_key,
                                    chat_id=msg.chat_id, voice=voice_name,
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

    def _voice_config_for(self, channel_name: str):
        """Get the VoiceConfig for a channel, or None."""
        ch_cfg = getattr(self.config.channels, channel_name, None)
        return getattr(ch_cfg, "voice", None)

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
