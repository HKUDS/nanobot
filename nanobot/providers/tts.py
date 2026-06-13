"""Provider-specific text-to-speech adapters.

This module only knows how to call external TTS APIs such as OpenAI TTS,
Groq/Orpheus, and ElevenLabs. Product-level config resolution, text validation,
and channel integration live in ``nanobot.audio.tts``.
"""

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

_SPEECH_PATH = "audio/speech"
_ELEVENLABS_DEFAULT_API_BASE = "https://api.elevenlabs.io/v1"

# Up to 3 retries with exponential backoff on transient failures.
_MAX_RETRIES = 3
_BACKOFF_S = (1.0, 2.0, 4.0)
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)


def _resolve_speech_url(api_base: str | None, default_url: str) -> str:
    """Resolve the full TTS endpoint URL.

    Accepts either a chat-style base (e.g. ``https://api.openai.com/v1``)
    or a complete URL already ending in ``/audio/speech``.
    """
    if not api_base:
        return default_url
    base = api_base.rstrip("/")
    if base.endswith(_SPEECH_PATH):
        return base
    return f"{base}/{_SPEECH_PATH}"


def _extract_error_detail(response: httpx.Response, provider_label: str) -> str:
    """Extract a human-readable error detail from a TTS error response.

    ElevenLabs returns structured JSON errors (e.g. model_deprecated_free_tier)
    that are much more informative than the raw status code. Parse those out
    so the log message is actionable.
    """
    body = response.text[:500]
    try:
        data = response.json()
        # ElevenLabs structured errors
        if isinstance(data, dict):
            detail = data.get("detail", {})
            if isinstance(detail, dict):
                code = detail.get("code", "")
                message = detail.get("message", "")
                if code and message:
                    return f"{code}: {message} ({body})"
            # Some endpoints return { "detail": { "status": ..., "message": ... } }
            if isinstance(detail, dict) and "message" in detail:
                return f"{detail.get('code', 'error')}: {detail['message']} ({body})"
            # Flat { "error": { "message": ... } } (OpenAI-style)
            err = data.get("error", {})
            if isinstance(err, dict) and "message" in err:
                return f"{err.get('type', 'error')}: {err['message']} ({body})"
    except Exception:
        pass
    return body


async def _request_audio_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    provider_label: str,
    **kwargs: Any,
) -> bytes | None:
    """POST to a TTS endpoint with retry logic, returning raw audio bytes."""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.post(url, **kwargs)
        except _RETRYABLE_EXCEPTIONS as e:
            if attempt < _MAX_RETRIES:
                logger.warning(
                    "{} TTS transient error (attempt {}/{}): {}",
                    provider_label,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    e,
                )
                await asyncio.sleep(_BACKOFF_S[attempt])
                continue
            logger.exception(
                "{} TTS error after {} attempts: {}",
                provider_label,
                _MAX_RETRIES + 1,
                e,
            )
            return None
        except Exception as e:
            logger.exception("{} TTS error: {}", provider_label, e)
            return None

        if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
            logger.warning(
                "{} TTS transient HTTP {} (attempt {}/{})",
                provider_label,
                response.status_code,
                attempt + 1,
                _MAX_RETRIES + 1,
            )
            retry_after = response.headers.get("retry-after")
            wait = float(retry_after) if retry_after else _BACKOFF_S[attempt]
            await asyncio.sleep(wait)
            continue

        if response.status_code >= 400:
            # Try to extract a structured error message from the response body
            detail = _extract_error_detail(response, provider_label)
            logger.error(
                "{} TTS HTTP {}: {}",
                provider_label,
                response.status_code,
                detail,
            )
            return None

        return response.content

    return None


class OpenAITTSProvider:
    """Text-to-speech provider using OpenAI's TTS API."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        response_format: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.api_url = _resolve_speech_url(
            api_base or os.environ.get("OPENAI_BASE_URL"),
            "https://api.openai.com/v1/audio/speech",
        )
        self.model = model or "tts-1"
        self.voice = (voice or "alloy").lower()
        self.response_format = (response_format or "mp3").lower()
        logger.debug("OpenAI TTS endpoint: {}", self.api_url)

    async def synthesize(self, text: str, output_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("OpenAI API key not configured for TTS")
            return ""

        payload: dict[str, Any] = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": self.response_format,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            audio_bytes = await _request_audio_with_retry(
                client,
                self.api_url,
                provider_label="OpenAI",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if not audio_bytes:
            return ""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
        return str(path)


class GroqTTSProvider:
    """Text-to-speech provider using Groq's Orpheus TTS API.

    Groq exposes an OpenAI-compatible ``/v1/audio/speech`` endpoint
    using the ``canopylabs/orpheus-v1-english`` model.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        response_format: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = _resolve_speech_url(
            api_base or os.environ.get("GROQ_BASE_URL"),
            "https://api.groq.com/openai/v1/audio/speech",
        )
        self.model = model or "canopylabs/orpheus-v1-english"
        self.voice = (voice or "autumn").lower()
        self.response_format = (response_format or "wav").lower()
        logger.debug("Groq TTS endpoint: {}", self.api_url)

    async def synthesize(self, text: str, output_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("Groq API key not configured for TTS")
            return ""

        async with httpx.AsyncClient(timeout=60.0) as client:
            audio_bytes = await _request_audio_with_retry(
                client,
                self.api_url,
                provider_label="Groq",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": text,
                    "voice": self.voice,
                    "response_format": self.response_format,
                },
            )

        if not audio_bytes:
            return ""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
        return str(path)


_ELEVENLABS_DEFAULT_VOICE = "Matilda"
_ELEVENLABS_DEFAULT_VOICE_ID = "XrExE9yKIg1WjnnlVkGX"


class ElevenLabsTTSProvider:
    """Text-to-speech provider using ElevenLabs API."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        response_format: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        self.api_base = (api_base or _ELEVENLABS_DEFAULT_API_BASE).rstrip("/")
        self.model = model or "eleven_multilingual_v2"
        self.voice = (voice or _ELEVENLABS_DEFAULT_VOICE)
        self.response_format = (response_format or "mp3").lower()
        logger.debug("ElevenLabs TTS base: {}", self.api_base)

    async def synthesize(self, text: str, output_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("ElevenLabs API key not configured for TTS")
            return ""

        # ElevenLabs requires a voice_id. If the user configured a voice name
        # (e.g. "Rachel"), we need to look up the voice_id first.
        voice_id = await self._resolve_voice_id()

        url = f"{self.api_base}/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": f"audio/{self.response_format}",
        }
        payload = {
            "text": text,
            "model_id": self.model,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            audio_bytes = await _request_audio_with_retry(
                client,
                url,
                provider_label="ElevenLabs",
                headers=headers,
                json=payload,
            )

        if not audio_bytes:
            return ""

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio_bytes)
        return str(path)

    async def _resolve_voice_id(self) -> str:
        """Resolve a voice name to an ElevenLabs voice_id.

        If the configured voice looks like a UUID, return it directly.
        Otherwise, look up the voice by name via the /voices endpoint.
        Falls back to the configured voice string if lookup fails.
        """
        voice = self.voice
        # UUID format check (8-4-4-4-12)
        import re

        if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", voice, re.I):
            return voice

        try:
            url = f"{self.api_base}/voices"
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    url,
                    headers={"xi-api-key": self.api_key},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for v in data.get("voices", []):
                        if v.get("name", "").lower() == voice.lower():
                            return v["voice_id"]
                else:
                    logger.warning(
                        "ElevenLabs voice list fetch failed (HTTP {}): {} — "
                        "ensure your API key has 'Voices Read' permission",
                        resp.status_code,
                        resp.text[:200],
                    )
        except Exception as e:
            logger.warning("ElevenLabs voice lookup failed: {}", e)

        logger.warning(
            "ElevenLabs: could not resolve voice '{}', falling back to default '{}'",
            voice,
            _ELEVENLABS_DEFAULT_VOICE_ID,
        )
        # If the configured voice name isn't found (e.g. an OpenAI voice name
        # like "nova" used with the ElevenLabs provider), fall back to the
        # provider default voice_id rather than sending an invalid name.
        return _ELEVENLABS_DEFAULT_VOICE_ID
