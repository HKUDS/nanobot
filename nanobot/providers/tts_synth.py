"""TTS synthesizer for Voice Server → ESP32 audio pipeline.

Supports:
  - edge: Microsoft Edge TTS (online, no API key needed)
  - openai: OpenAI-compatible TTS API (Speaches-AI / Piper on local server)

Usage:
    synth = TTSSynthesizer(config.tools.tts)
    audio_bytes = await synth.synthesize("Привет, мир!")
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import TTSConfig


class TTSSynthesizer:
    """Converts text to PCM/Opus audio bytes using configured TTS backend."""

    def __init__(self, tts_config: "TTSConfig"):
        self.config = tts_config

    def _get_preset(self):
        """Return active TTSVoiceConfig preset or None."""
        if not self.config or not self.config.active_preset:
            return None
        return self.config.presets.get(self.config.active_preset)

    async def synthesize(self, text: str) -> bytes | None:
        """Synthesize text to audio. Returns raw MP3/Opus bytes or None on failure."""
        preset = self._get_preset()
        if preset is None:
            logger.warning("TTS: no active_preset configured, cannot synthesize")
            return None

        provider = preset.provider.lower()
        try:
            if provider == "edge":
                return await self._edge_tts(text, preset.voice)
            elif provider in ("openai", "speaches", "piper"):
                return await self._openai_tts(text, preset)
            else:
                logger.warning(f"TTS: unknown provider '{provider}'")
                return None
        except Exception as e:
            logger.error(f"TTS synthesis failed ({provider}): {e}")
            return None

    async def _edge_tts(self, text: str, voice: str) -> bytes:
        """Synthesize via Microsoft Edge TTS (free, online) and return PCM bytes."""
        try:
            import edge_tts  # type: ignore
        except ImportError:
            raise RuntimeError(
                "edge-tts not installed. Run: pip install edge-tts"
            )

        # Force Communicate to use raw-16khz-16bit-mono-pcm instead of default mp3
        # The library uses these constants internally to request specific formats from the service.
        communicate = edge_tts.Communicate(text, voice)
        
        # In newer edge-tts versions, we can patch the internal format or use sub-classes.
        # But usually, it uses a constant for the WSS request. 
        # Let's try to find if we can just pass it.
        # Based on search results, 'raw-16khz-16bit-mono-pcm' is a valid format string.
        
        audio_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes += chunk["data"]
        
        if not audio_bytes:
             raise RuntimeError("edge-tts returned empty audio")

        logger.debug(f"TTS (edge): synthesized {len(audio_bytes)} bytes ('{text[:40]}...')")
        return audio_bytes

    async def _openai_tts(self, text: str, preset) -> bytes:
        """Synthesize via OpenAI-compatible TTS API (e.g. Speaches-AI/Piper)."""
        import httpx

        api_base = preset.api_base or "http://whisper-server:8000/v1"
        # Strip trailing /v1 if needed for endpoint construction
        base = api_base.rstrip("/")
        if not base.endswith("/audio/speech"):
            base = base.rstrip("/v1").rstrip("/")
            url = f"{base}/v1/audio/speech"
        else:
            url = base

        model = preset.model or "speaches-ai/piper-ru_RU-irina-medium"
        voice = preset.voice or "irina"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json={
                    "model": model,
                    "input": text,
                    "voice": voice,
                    "response_format": "wav",
                },
            )
            resp.raise_for_status()
            audio_bytes = resp.content
            if not audio_bytes:
                raise RuntimeError("OpenAI TTS API returned empty audio")

            # Handle WAV: strip header and resample if needed
            if audio_bytes.startswith(b"RIFF"):
                import wave
                import audioop
                
                with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
                    params = wav.getparams()
                    raw_data = wav.readframes(params.nframes)
                    
                    # Ensure mono 16-bit
                    if params.nchannels > 1:
                        raw_data = audioop.tomono(raw_data, params.sampwidth, 1, 1)
                    
                    if params.sampwidth != 2:
                        raw_data = audioop.lin2lin(raw_data, params.sampwidth, 2)
                        
                    # Resample to 16kHz if needed
                    if params.framerate != 16000:
                        logger.debug(f"TTS: resampling from {params.framerate}Hz to 16000Hz")
                        raw_data, _ = audioop.ratecv(raw_data, 2, 1, params.framerate, 16000, None)
                    
                    audio_bytes = raw_data

            logger.debug(f"TTS (openai): finalized {len(audio_bytes)} PCM bytes from {url}")
            return audio_bytes
