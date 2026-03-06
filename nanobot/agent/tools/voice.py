"""Text-to-speech voice generation tool via Google Gemini TTS."""

from __future__ import annotations

import asyncio
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

_MEDIA_ROOT = Path.home() / ".nanobot" / "media"

_TTS_SAMPLE_RATE = 24000
_TTS_CHANNELS = 1
_TTS_SAMPLE_WIDTH = 2


def _get_gemini_key() -> str:
    """Resolve Gemini API key from config."""
    from nanobot.config.loader import load_config

    try:
        return load_config().providers.gemini.api_key or ""
    except Exception:
        return ""


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


# ── Voice catalogue ──────────────────────────────────────────────────────────
# Gender labels sourced from Google Cloud TTS documentation.

FEMALE_VOICES: dict[str, str] = {
    "Achernar": "Soft",
    "Aoede": "Breezy",
    "Autonoe": "Bright",
    "Callirrhoe": "Easy-going",
    "Despina": "Smooth",
    "Erinome": "Clear",
    "Gacrux": "Mature",
    "Kore": "Firm",
    "Laomedeia": "Upbeat",
    "Leda": "Youthful",
    "Pulcherrima": "Forward",
    "Sulafat": "Warm",
    "Vindemiatrix": "Gentle",
    "Zephyr": "Bright",
}

MALE_VOICES: dict[str, str] = {
    "Achird": "Friendly",
    "Algenib": "Gravelly",
    "Algieba": "Smooth",
    "Alnilam": "Firm",
    "Charon": "Informative",
    "Enceladus": "Breathy",
    "Fenrir": "Excitable",
    "Iapetus": "Clear",
    "Orus": "Firm",
    "Puck": "Upbeat",
    "Rasalgethi": "Informative",
    "Sadachbia": "Lively",
    "Sadaltager": "Knowledgeable",
    "Schedar": "Even",
    "Umbriel": "Easy-going",
    "Zubenelgenubi": "Casual",
}

ALL_VOICES: dict[str, str] = {**FEMALE_VOICES, **MALE_VOICES}
_VOICE_NAMES = sorted(ALL_VOICES.keys())


def _voice_description() -> str:
    """Build a description string listing all voices with gender and tone."""
    female = ", ".join(f"{n} ({t})" for n, t in sorted(FEMALE_VOICES.items()))
    male = ", ".join(f"{n} ({t})" for n, t in sorted(MALE_VOICES.items()))
    return (
        f"Female voices: {female}. "
        f"Male voices: {male}."
    )


# ── Tool ─────────────────────────────────────────────────────────────────────


class GenerateVoiceTool(Tool):

    @property
    def name(self) -> str:
        return "generate_voice"

    @property
    def description(self) -> str:
        return (
            "Generate speech audio from text using Google Gemini TTS. "
            "Choose from 30 voices (14 female, 16 male). "
            "Returns the file path of the generated audio (WAV). "
            "Use the message tool with media=[path] to send the audio to the user. "
            + _voice_description()
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to speak aloud",
                },
                "voice": {
                    "type": "string",
                    "enum": _VOICE_NAMES,
                    "description": (
                        "Voice to use. Pick a different voice each time for variety. "
                        "Female: Kore (Firm), Aoede (Breezy), Zephyr (Bright), Leda (Youthful), Sulafat (Warm). "
                        "Male: Charon (Informative), Puck (Upbeat), Fenrir (Excitable), Orus (Firm), Achird (Friendly)."
                    ),
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> str:
        text = kwargs.get("text", "")
        voice = kwargs.get("voice", "Kore")

        if voice not in ALL_VOICES:
            voice = "Kore"

        api_key = _get_gemini_key()
        if not api_key:
            return (
                "Error: Gemini API key not configured. "
                "Set it in ~/.nanobot/config.json under providers.gemini.apiKey"
            )

        out_dir = _MEDIA_ROOT / "voice"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model="gemini-2.5-flash-preview-tts",
                    contents=text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice,
                                )
                            )
                        ),
                    ),
                ),
            )

            audio_data = response.candidates[0].content.parts[0].inline_data.data

            ts = _ts()
            gender = "F" if voice in FEMALE_VOICES else "M"
            tone = ALL_VOICES[voice].lower().replace(" ", "")
            out_path = out_dir / f"voice_{ts}_{voice.lower()}_{gender}_{tone}.wav"

            with wave.open(str(out_path), "wb") as wf:
                wf.setnchannels(_TTS_CHANNELS)
                wf.setsampwidth(_TTS_SAMPLE_WIDTH)
                wf.setframerate(_TTS_SAMPLE_RATE)
                wf.writeframes(audio_data)

            duration = len(audio_data) / (_TTS_SAMPLE_RATE * _TTS_CHANNELS * _TTS_SAMPLE_WIDTH)
            gender_label = "female" if voice in FEMALE_VOICES else "male"
            logger.info(
                "Generated voice: {} ({:.1f}s, voice={}, gender={}, tone={})",
                out_path, duration, voice, gender_label, ALL_VOICES[voice],
            )
            return str(out_path)

        except Exception as e:
            logger.error("Voice generation failed: {}", e)
            return f"Error generating voice: {e}"
