"""Voice transcription providers (Groq, OpenAI Whisper, Xiaomi MiMo ASR)."""

import asyncio
import base64
import json
import os
from pathlib import Path

import httpx
from loguru import logger

_TRANSCRIPTIONS_PATH = "audio/transcriptions"
_CHAT_COMPLETIONS_PATH = "chat/completions"


def _resolve_transcription_url(api_base: str | None, default_url: str) -> str:
    """Resolve the full transcription endpoint URL.

    Accepts either a chat-style base (e.g. ``https://api.groq.com/openai/v1``)
    or a complete URL already ending in ``/audio/transcriptions``. A chat-style
    base — the form users naturally copy from their LLM provider config — gets
    the path appended instead of being POSTed verbatim and 404ing (#3637).
    """
    if not api_base:
        return default_url
    base = api_base.rstrip("/")
    if base.endswith(_TRANSCRIPTIONS_PATH):
        return base
    return f"{base}/{_TRANSCRIPTIONS_PATH}"


# Up to 3 retries (4 attempts total) with exponential backoff on transient
# failures. Whisper endpoints occasionally return 502/503 under load, and
# mobile-network transcription callers hit sporadic connect/read errors.
# Without this, a voice message silently becomes the empty string.
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


async def _post_transcription_with_retry(
    url: str,
    *,
    api_key: str | None,
    path: Path,
    model: str,
    provider_label: str,
    language: str | None = None,
) -> str:
    """POST an audio file for transcription, retrying on transient errors.

    Retries on connect/read/timeout failures and on 408/429/5xx responses.
    Other errors (including 4xx such as 401/403) return "" immediately — the
    caller's config is wrong and retrying only wastes quota.

    When ``language`` is provided, it is forwarded as the ``language``
    multipart field on every attempt (the dict is rebuilt per attempt so the
    same field is present on retries).
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.exception("{} transcription error: cannot read audio file: {}", provider_label, e)
        return ""
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient() as client:
        for attempt in range(_MAX_RETRIES + 1):
            files = {
                "file": (path.name, data),
                "model": (None, model),
            }
            if language:
                files["language"] = (None, language)
            try:
                response = await client.post(url, headers=headers, files=files, timeout=60.0)
            except _RETRYABLE_EXCEPTIONS as e:
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "{} transcription transient error (attempt {}/{}): {}",
                        provider_label,
                        attempt + 1,
                        _MAX_RETRIES + 1,
                        e,
                    )
                    await asyncio.sleep(_BACKOFF_S[attempt])
                    continue
                logger.exception(
                    "{} transcription error after {} attempts: {}",
                    provider_label,
                    _MAX_RETRIES + 1,
                    e,
                )
                return ""
            except Exception as e:
                logger.exception("{} transcription error: {}", provider_label, e)
                return ""

            if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                logger.warning(
                    "{} transcription transient HTTP {} (attempt {}/{})",
                    provider_label,
                    response.status_code,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                )
                await asyncio.sleep(_BACKOFF_S[attempt])
                continue

            try:
                response.raise_for_status()
            except Exception as e:
                logger.exception("{} transcription error: {}", provider_label, e)
                return ""

            try:
                payload = response.json()
            except Exception as e:
                logger.exception(
                    "{} transcription error: malformed response body: {}",
                    provider_label,
                    e,
                )
                return ""
            if not isinstance(payload, dict):
                logger.error(
                    "{} transcription error: unexpected response shape: {!r}",
                    provider_label,
                    type(payload).__name__,
                )
                return ""
            return payload.get("text", "")


class OpenAITranscriptionProvider:
    """Voice transcription provider using OpenAI's Whisper API."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.api_url = _resolve_transcription_url(
            api_base or os.environ.get("OPENAI_TRANSCRIPTION_BASE_URL"),
            "https://api.openai.com/v1/audio/transcriptions",
        )
        self.language = language or None
        logger.debug("OpenAI transcription endpoint: {}", self.api_url)

    async def transcribe(self, file_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("OpenAI API key not configured for transcription")
            return ""
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""
        return await _post_transcription_with_retry(
            self.api_url,
            api_key=self.api_key,
            path=path,
            model="whisper-1",
            provider_label="OpenAI",
            language=self.language,
        )


class GroqTranscriptionProvider:
    """
    Voice transcription provider using Groq's Whisper API.

    Groq offers extremely fast transcription with a generous free tier.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = _resolve_transcription_url(
            api_base or os.environ.get("GROQ_BASE_URL"),
            "https://api.groq.com/openai/v1/audio/transcriptions",
        )
        self.language = language or None
        logger.debug("Groq transcription endpoint: {}", self.api_url)

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using Groq.

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text.
        """
        if not self.api_key:
            logger.warning("Groq API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        return await _post_transcription_with_retry(
            self.api_url,
            api_key=self.api_key,
            path=path,
            model="whisper-large-v3",
            provider_label="Groq",
            language=self.language,
        )


def _resolve_chat_completions_url(api_base: str | None, default_url: str) -> str:
    """Resolve the chat completions endpoint URL for Xiaomi ASR."""
    if not api_base:
        return default_url
    base = api_base.rstrip("/")
    if base.endswith(_CHAT_COMPLETIONS_PATH):
        return base
    return f"{base}/{_CHAT_COMPLETIONS_PATH}"


async def _post_xiaomi_asr_with_retry(
    url: str,
    *,
    api_key: str | None,
    path: Path,
    model: str,
    provider_label: str,
    language: str | None = None,
) -> str:
    """POST audio to Xiaomi MiMo ASR endpoint via chat completions API.

    Xiaomi MiMo ASR uses the /v1/chat/completions endpoint with base64-encoded
    audio in input_audio format, rather than the standard Whisper multipart upload.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.exception("{} transcription error: cannot read audio file: {}", provider_label, e)
        return ""

    audio_b64 = base64.b64encode(data).decode("ascii")

    # Determine MIME type from file extension
    suffix = path.suffix.lower()
    mime_map = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
    }
    mime_type = mime_map.get(suffix, "audio/wav")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body: dict = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:{mime_type};base64,{audio_b64}",
                        },
                    }
                ],
            }
        ],
    }
    if language:
        body["asr_options"] = {"language": language}

    async with httpx.AsyncClient() as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.post(
                    url, headers=headers, content=json.dumps(body), timeout=60.0
                )
            except _RETRYABLE_EXCEPTIONS as e:
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "{} transcription transient error (attempt {}/{}): {}",
                        provider_label,
                        attempt + 1,
                        _MAX_RETRIES + 1,
                        e,
                    )
                    await asyncio.sleep(_BACKOFF_S[attempt])
                    continue
                logger.exception(
                    "{} transcription error after {} attempts: {}",
                    provider_label,
                    _MAX_RETRIES + 1,
                    e,
                )
                return ""
            except Exception as e:
                logger.exception("{} transcription error: {}", provider_label, e)
                return ""

            if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                logger.warning(
                    "{} transcription transient HTTP {} (attempt {}/{})",
                    provider_label,
                    response.status_code,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                )
                await asyncio.sleep(_BACKOFF_S[attempt])
                continue

            try:
                response.raise_for_status()
            except Exception as e:
                logger.exception("{} transcription error: {}", provider_label, e)
                return ""

            try:
                payload = response.json()
            except Exception as e:
                logger.exception(
                    "{} transcription error: malformed response body: {}",
                    provider_label,
                    e,
                )
                return ""

            # Extract text from chat completions response format
            try:
                return payload["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                logger.error(
                    "{} transcription error: unexpected response shape: {!r}",
                    provider_label,
                    payload,
                )
                return ""


class XiaomiASRTranscriptionProvider:
    """Voice transcription provider using Xiaomi MiMo ASR API.

    Unlike Whisper-compatible providers, Xiaomi MiMo ASR uses the
    /v1/chat/completions endpoint with base64-encoded audio input.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("MIMO_API_KEY")
        self.api_url = _resolve_chat_completions_url(
            api_base or os.environ.get("MIMO_API_BASE"),
            "https://api.xiaomimimo.com/v1/chat/completions",
        )
        self.language = language or "zh"
        logger.debug("Xiaomi ASR transcription endpoint: {}", self.api_url)

    async def transcribe(self, file_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("Xiaomi API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        return await _post_xiaomi_asr_with_retry(
            self.api_url,
            api_key=self.api_key,
            path=path,
            model="mimo-v2.5-asr",
            provider_label="Xiaomi ASR",
            language=self.language,
        )
