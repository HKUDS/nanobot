"""Voice transcription providers and selector."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
from loguru import logger


class BaseTranscriptionProvider:
    """Shared interface for audio transcription backends."""

    name = "base"

    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe *file_path* and return text, or an empty string on failure."""
        raise NotImplementedError


class GroqTranscriptionProvider(BaseTranscriptionProvider):
    """Voice transcription provider using Groq's Whisper API."""

    name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = "whisper-large-v3",
        language: str | None = None,
        prompt: str | None = None,
        temperature: float | None = None,
        timeout_s: float = 60.0,
    ):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"
        self.model = model
        self.language = language
        self.prompt = prompt
        self.temperature = temperature
        self.timeout_s = timeout_s

    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file using Groq."""
        if not self.api_key:
            logger.warning("Groq API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f),
                        "model": (None, self.model),
                    }
                    data: dict[str, str] = {}
                    if self.language:
                        data["language"] = self.language
                    if self.prompt:
                        data["prompt"] = self.prompt
                    if self.temperature is not None:
                        data["temperature"] = str(self.temperature)
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        data=data or None,
                        timeout=self.timeout_s,
                    )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")

        except Exception as e:
            logger.error("Groq transcription error: {}", e)
            return ""


class LocalFasterWhisperTranscriptionProvider(BaseTranscriptionProvider):
    """Local transcription provider backed by faster-whisper."""

    name = "faster-whisper"

    def __init__(
        self,
        *,
        model: str = "small",
        device: str = "auto",
        compute_type: str = "default",
        cpu_threads: int = 0,
        download_root: str | None = None,
        language: str | None = None,
        beam_size: int = 5,
    ):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.download_root = download_root
        self.language = language
        self.beam_size = beam_size
        self._model = None
        self._load_lock = asyncio.Lock()

    @staticmethod
    def is_available() -> bool:
        """Return True when faster-whisper can be imported."""
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    async def _ensure_model(self):
        if self._model is not None:
            return self._model

        async with self._load_lock:
            if self._model is not None:
                return self._model

            def _load():
                from faster_whisper import WhisperModel

                kwargs: dict[str, Any] = {
                    "device": self.device,
                    "compute_type": self.compute_type,
                }
                if self.cpu_threads:
                    kwargs["cpu_threads"] = self.cpu_threads
                if self.download_root:
                    kwargs["download_root"] = self.download_root
                return WhisperModel(self.model_name, **kwargs)

            self._model = await asyncio.to_thread(_load)
            return self._model

    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file locally with faster-whisper."""
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""
        if not self.is_available():
            logger.warning("faster-whisper is not installed; local transcription unavailable")
            return ""

        try:
            model = await self._ensure_model()

            def _transcribe() -> str:
                kwargs: dict[str, Any] = {"beam_size": self.beam_size}
                if self.language:
                    kwargs["language"] = self.language
                segments, _ = model.transcribe(str(path), **kwargs)
                return " ".join(
                    segment.text.strip()
                    for segment in segments
                    if getattr(segment, "text", "").strip()
                ).strip()

            return await asyncio.to_thread(_transcribe)
        except Exception as e:
            logger.error("Local faster-whisper transcription error: {}", e)
            return ""


def resolve_transcription_provider(config: Any) -> BaseTranscriptionProvider | None:
    """Resolve the configured transcription backend for *config*."""
    transcriber = _get_nested(config, "agents", "defaults", "transcriber", default="auto")

    if transcriber == "faster-whisper":
        return _build_faster_whisper_provider(config, log_failures=True)
    if transcriber == "groq":
        return _build_groq_provider(config, log_failures=True)

    faster_whisper_provider = _build_faster_whisper_provider(config, log_failures=False)
    if faster_whisper_provider is not None:
        return faster_whisper_provider
    groq_provider = _build_groq_provider(config, log_failures=False)
    if groq_provider is not None:
        return groq_provider
    return None


def _build_faster_whisper_provider(
    config: Any,
    *,
    log_failures: bool,
) -> LocalFasterWhisperTranscriptionProvider | None:
    if not LocalFasterWhisperTranscriptionProvider.is_available():
        if log_failures:
            logger.warning("Local transcription requested but faster-whisper is not installed")
        return None

    faster_whisper = _get_nested(config, "transcription", "faster-whisper")
    kwargs = {
        "model": _get_nested(faster_whisper, "model", default="small"),
        "device": _get_nested(faster_whisper, "device", default="auto"),
        "compute_type": _get_nested(faster_whisper, "compute_type", default="default"),
        "cpu_threads": _get_nested(faster_whisper, "cpu_threads", default=0),
        "download_root": _get_nested(faster_whisper),
        "language": _get_nested(faster_whisper, "language", default=None),
        "beam_size": _get_nested(faster_whisper, "beam_size", default=5),
    }
    return LocalFasterWhisperTranscriptionProvider(**kwargs)


def _build_groq_provider(
    config: Any,
    *,
    log_failures: bool,
) -> GroqTranscriptionProvider | None:
    api_key = _get_nested(config, "providers", "groq", "api_key", default="") or os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        if log_failures:
            logger.warning("Groq transcription requested but no API key is configured")
        return None

    groq = _get_nested(config, "transcription", "groq")
    kwargs = {
        "api_key": api_key,
        "model": _get_nested(groq, "model", default="whisper-large-v3"),
        "language": _get_nested(groq, "language", default=None),
        "prompt": _get_nested(groq, "prompt", default=None),
        "temperature": _get_nested(groq, "temperature", default=None),
        "timeout_s": _get_nested(groq, "timeout_s", default=60.0),
    }
    return GroqTranscriptionProvider(**kwargs)


def _get_nested(obj: Any, *parts: str, default: Any = None) -> Any:
    current = obj
    for part in parts:
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(part, default)
        else:
            current = getattr(current, part, default)
    return current
