"""Voice transcription providers (cloud and local Whisper-compatible).

Supports three provider modes:

- **groq**: Groq's hosted Whisper API (fast, generous free tier).
- **openai**: OpenAI's Whisper API.
- **local**: Any OpenAI-compatible Whisper endpoint running locally — e.g.
  `whisper.cpp <https://github.com/ggerganov/whisper.cpp>`_ server,
  `faster-whisper-server <https://github.com/fedirz/faster-whisper-server>`_,
  `LocalAI <https://localai.io>`_, or Ollama with a Whisper model.

Local setup examples::

    # whisper.cpp server (default port 8080)
    ./server -m ggml-large-v3.bin --port 8080
    # → provider: local, api_base: http://localhost:8080/v1/audio/transcriptions

    # faster-whisper-server
    faster-whisper-server --model large-v3
    # → provider: local, api_base: http://localhost:8000/v1/audio/transcriptions

    # LocalAI
    local-ai run whisper-1
    # → provider: local, api_base: http://localhost:8080/v1/audio/transcriptions
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from loguru import logger

# ---------------------------------------------------------------------------
# Provider defaults
# ---------------------------------------------------------------------------

_PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "groq": {
        "api_base": "https://api.groq.com/openai/v1/audio/transcriptions",
        "model": "whisper-large-v3",
        "env_key": "GROQ_API_KEY",
        "env_base": "GROQ_BASE_URL",
    },
    "openai": {
        "api_base": "https://api.openai.com/v1/audio/transcriptions",
        "model": "whisper-1",
        "env_key": "OPENAI_API_KEY",
        "env_base": "OPENAI_TRANSCRIPTION_BASE_URL",
    },
    "local": {
        "api_base": "",  # required — user must supply
        "model": "whisper-large-v3",
        "env_key": "",
        "env_base": "",
    },
}


class WhisperTranscriptionProvider:
    """Unified Whisper-compatible transcription provider.

    Works with any OpenAI-compatible ``/v1/audio/transcriptions`` endpoint,
    including Groq, OpenAI, whisper.cpp, faster-whisper-server, and LocalAI.

    Args:
        provider: Provider name — ``"groq"``, ``"openai"``, or ``"local"``.
        api_key: API key. Falls back to the provider's env var. Not required
            for ``local``.
        api_base: Endpoint URL. Falls back to provider default / env var.
            **Required** for ``local``.
        model: Whisper model name. Falls back to provider default.
        language: Optional ISO-639-1 language hint (e.g. ``"en"``, ``"ar"``).
        max_duration_seconds: Reject files longer than this (by file size
            heuristic). Set 0 to disable.
    """

    def __init__(
        self,
        provider: str = "groq",
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        language: str | None = None,
        max_duration_seconds: int = 300,
    ):
        defaults = _PROVIDER_DEFAULTS.get(provider, _PROVIDER_DEFAULTS["groq"])

        self.provider = provider
        self.api_key = (
            api_key
            or (os.environ.get(defaults["env_key"]) if defaults["env_key"] else None)
            or None
        )
        self.api_url = (
            api_base
            or (os.environ.get(defaults["env_base"]) if defaults["env_base"] else None)
            or defaults["api_base"]
        )
        self.model = model or defaults["model"]
        self.language = language or None
        self.max_duration_seconds = max_duration_seconds

    @property
    def is_available(self) -> bool:
        """Check if this provider is ready to transcribe."""
        if self.provider == "local":
            return bool(self.api_url)
        return bool(self.api_key) and bool(self.api_url)

    @property
    def unavailable_reason(self) -> str:
        """Human-readable explanation of why transcription is unavailable."""
        if self.provider == "local":
            if not self.api_url:
                return "Local transcription requires api_base (e.g. http://localhost:8080/v1/audio/transcriptions)"
        else:
            if not self.api_key:
                return f"No API key configured for {self.provider} transcription"
            if not self.api_url:
                return f"No API base URL configured for {self.provider} transcription"
        return ""

    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file.

        Returns the transcribed text, or an empty string on failure.
        """
        if not self.is_available:
            reason = self.unavailable_reason
            logger.warning("Transcription unavailable: {}", reason)
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        # Rough duration guard — assume worst case ~16 kB/s for voice audio
        if self.max_duration_seconds > 0:
            file_size = path.stat().st_size
            estimated_seconds = file_size / 16_000
            if estimated_seconds > self.max_duration_seconds:
                logger.warning(
                    "Audio file too long (~{:.0f}s estimated, max {}s): {}",
                    estimated_seconds,
                    self.max_duration_seconds,
                    file_path,
                )
                return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files: dict = {
                        "file": (path.name, f),
                        "model": (None, self.model),
                    }
                    if self.language:
                        files["language"] = (None, self.language)

                    headers: dict[str, str] = {}
                    if self.api_key:
                        headers["Authorization"] = f"Bearer {self.api_key}"

                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        timeout=60.0,
                    )
                    response.raise_for_status()
                    return response.json().get("text", "")
        except Exception as e:
            logger.error("{} transcription error: {}", self.provider, e)
            return ""


# ---------------------------------------------------------------------------
# Backward-compatible aliases (deprecated)
# ---------------------------------------------------------------------------


class GroqTranscriptionProvider(WhisperTranscriptionProvider):
    """Deprecated: use :class:`WhisperTranscriptionProvider` with ``provider="groq"``.

    Kept for backward compatibility with existing imports.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
    ):
        super().__init__(
            "groq",
            api_key=api_key,
            api_base=api_base,
            language=language,
        )


class OpenAITranscriptionProvider(WhisperTranscriptionProvider):
    """Deprecated: use :class:`WhisperTranscriptionProvider` with ``provider="openai"``.

    Kept for backward compatibility with existing imports.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
    ):
        super().__init__(
            "openai",
            api_key=api_key,
            api_base=api_base,
            language=language,
        )
