"""Text-to-speech provider — Groq Orpheus TTS primary, Edge TTS fallback."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx
from loguru import logger

# Groq Orpheus voice map — friendly names to Orpheus voice names
# Native Orpheus voices: tara, leah, jess, leo, dan, mia, zac, zoe
# Legacy aliases (aria, jenny, etc.) map to closest Orpheus voice
GROQ_VOICES: dict[str, str] = {
    "tara":  "tara",
    "leah":  "leah",
    "jess":  "jess",
    "leo":   "leo",
    "dan":   "dan",
    "mia":   "mia",
    "zac":   "zac",
    "zoe":   "zoe",
    # Legacy PlayAI aliases → nearest Orpheus voice
    "aria":  "tara",
    "jenny": "leah",
    "sonia": "jess",
    "guy":   "leo",
    "ryan":  "dan",
    "davis": "dan",
}

# Edge TTS voice map — fallback when Groq is unavailable
EDGE_VOICES: dict[str, str] = {
    "aria":  "en-US-AriaNeural",
    "jenny": "en-US-JennyNeural",
    "sonia": "en-GB-SoniaNeural",
    "guy":   "en-US-GuyNeural",
    "ryan":  "en-GB-RyanNeural",
    "davis": "en-US-DavisNeural",
    "tara":  "en-US-AriaNeural",
    "leah":  "en-US-JennyNeural",
    "jess":  "en-US-JennyNeural",
    "leo":   "en-US-GuyNeural",
    "dan":   "en-US-DavisNeural",
    "mia":   "en-US-AriaNeural",
    "zac":  "en-GB-RyanNeural",
    "zoe":   "en-GB-SoniaNeural",
}

DEFAULT_VOICE = "tara"

GROQ_TTS_URL = "https://api.groq.com/openai/v1/audio/speech"
GROQ_TTS_MODEL = "canopylabs/orpheus-v1-english"


def _to_ogg(mp3_path: Path) -> Path | None:
    """Convert MP3 to OGG Opus using ffmpeg. Returns OGG path or None on failure."""
    ogg_path = mp3_path.with_suffix(".ogg")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(mp3_path), "-c:a", "libopus", str(ogg_path)],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and ogg_path.exists():
            mp3_path.unlink(missing_ok=True)
            logger.info("OGG conversion successful: {} ({} bytes)", ogg_path.name, ogg_path.stat().st_size)
            return ogg_path
        logger.error("ffmpeg conversion failed: {}", result.stderr.decode()[:200])
    except Exception as e:
        logger.error("ffmpeg error: {}", e)
    return None


async def _synthesize_groq(text: str, voice: str, file_path: Path, api_key: str) -> bool:
    """Generate audio using Groq Orpheus TTS."""
    try:
        voice_id = GROQ_VOICES.get(voice.lower(), GROQ_VOICES.get(DEFAULT_VOICE, DEFAULT_VOICE))
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GROQ_TTS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": GROQ_TTS_MODEL, "input": text, "voice": voice_id, "response_format": "mp3"},
                timeout=60.0,
            )
            response.raise_for_status()
            file_path.write_bytes(response.content)
            logger.info("Groq TTS generated: {} ({} bytes)", file_path.name, len(response.content))
            return True
    except Exception as e:
        logger.warning("Groq TTS unavailable ({}), falling back to Edge TTS", e)
        return False


async def _synthesize_edge(text: str, voice: str, file_path: Path) -> bool:
    """Generate MP3 using Microsoft Edge TTS (free, no API key)."""
    try:
        import edge_tts
        voice_id = EDGE_VOICES.get(voice.lower(), EDGE_VOICES[DEFAULT_VOICE])
        communicate = edge_tts.Communicate(text, voice=voice_id)
        await communicate.save(str(file_path))
        logger.info("Edge TTS generated: {} ({} bytes)", file_path.name, file_path.stat().st_size)
        return True
    except Exception as e:
        logger.error("Edge TTS error: {}", e)
        return False


class GroqTTSProvider:
    """
    TTS provider — tries Groq Orpheus first, falls back to Edge TTS.
    Always outputs OGG Opus so Telegram delivers it as a voice bubble.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")

    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        output_dir: Path | None = None,
    ) -> Path | None:
        if not text or not text.strip():
            logger.warning("TTS called with empty text")
            return None

        save_dir = output_dir or (Path.home() / ".nanobot" / "media")
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        mp3_path = save_dir / f"tts_{ts}.mp3"

        ok = False

        # Try Groq Orpheus first
        if self.api_key:
            ok = await _synthesize_groq(text, voice, mp3_path, self.api_key)

        # Fall back to Edge TTS
        if not ok:
            ok = await _synthesize_edge(text, voice, mp3_path)

        if not ok:
            return None

        # Convert MP3 → OGG so Telegram shows a voice bubble
        ogg = await asyncio.to_thread(_to_ogg, mp3_path)
        if ogg:
            return ogg

        # If ffmpeg not available, return MP3 (shows as audio file, needs tap)
        logger.warning("ffmpeg not available — returning MP3 (no voice bubble)")
        return mp3_path
