"""Provider-specific voice transcription adapters.

This module only knows how to call external transcription APIs such as Groq,
OpenAI Whisper, OpenRouter, Xiaomi MiMo ASR, and AssemblyAI. Product-level config fallback,
WebUI upload validation, and channel integration live in
``blackcat.audio.transcription``.
"""

import asyncio
import base64
import json
import mimetypes
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

_CHAT_COMPLETIONS_PATH = "chat/completions"
_TRANSCRIPTIONS_PATH = "audio/transcriptions"
_ASSEMBLYAI_DEFAULT_API_BASE = "https://api.assemblyai.com/v2"
_ASSEMBLYAI_POLL_ATTEMPTS = 60
_ASSEMBLYAI_POLL_INTERVAL_S = 2.0
_AUDIO_MIME_OVERRIDES = {
    ".m4a": "audio/mp4",
    ".mpga": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".weba": "audio/webm",
    ".webm": "audio/webm",
}
_FORMAT_ALIASES = {
    "oga": "ogg",
    "opus": "ogg",
    "mpga": "mp3",
    "mpeg": "mp3",
    "mp4": "m4a",
}


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


def _resolve_chat_completions_url(api_base: str | None, default_url: str) -> str:
    """Resolve a chat-completions endpoint for ASR providers using chat payloads."""
    if not api_base:
        return default_url
    base = api_base.rstrip("/")
    if base.endswith(_CHAT_COMPLETIONS_PATH):
        return base
    return f"{base}/{_CHAT_COMPLETIONS_PATH}"


def _resolve_api_path(api_base: str | None, default_base: str, path: str) -> str:
    base = (api_base or default_base).rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _audio_mime_type(path: Path) -> str:
    return (
        _AUDIO_MIME_OVERRIDES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def _audio_format(path: Path) -> str:
    """Map an audio file's extension to an OpenRouter ``format`` value."""
    ext = path.suffix.lstrip(".").lower()
    return _FORMAT_ALIASES.get(ext, ext)


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


async def _request_json_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider_label: str,
    **kwargs: object,
) -> dict[str, Any] | None:
    for attempt in range(_MAX_RETRIES + 1):
        try:
            request = getattr(client, method.lower(), None)
            if request is None:
                response = await client.request(method, url, **kwargs)
            else:
                response = await request(url, **kwargs)
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
            return None
        except Exception as e:
            logger.exception("{} transcription error: {}", provider_label, e)
            return None

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
        except httpx.HTTPStatusError:
            body = response.text.strip().replace("\n", " ")[:500]
            logger.error(
                "{} transcription HTTP {}{}{}",
                provider_label,
                response.status_code,
                f" {response.reason_phrase}" if response.reason_phrase else "",
                f": {body}" if body else "",
            )
            return None
        except Exception as e:
            logger.exception("{} transcription error: {}", provider_label, e)
            return None

        try:
            payload = response.json()
        except Exception as e:
            logger.exception(
                "{} transcription error: malformed response body: {}",
                provider_label,
                e,
            )
            return None
        if not isinstance(payload, dict):
            logger.error(
                "{} transcription error: unexpected response shape: {!r}",
                provider_label,
                type(payload).__name__,
            )
            return None
        return payload
    return None


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

    def build_request() -> dict[str, Any]:
        files = {
            "file": (path.name, data, _audio_mime_type(path)),
            "model": (None, model),
        }
        if language:
            files["language"] = (None, language)
        return {"url": url, "headers": headers, "files": files, "timeout": 60.0}

    return await _post_with_retry(build_request, provider_label, _text_from_transcription_payload)


async def _post_json_transcription_with_retry(
    url: str,
    *,
    api_key: str | None,
    path: Path,
    model: str,
    provider_label: str,
    language: str | None = None,
) -> str:
    """POST base64 JSON audio for providers that do not accept multipart uploads."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.exception("{} transcription error: cannot read audio file: {}", provider_label, e)
        return ""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def build_request() -> dict[str, Any]:
        body: dict[str, object] = {
            "model": model,
            "input_audio": {
                "data": base64.b64encode(data).decode(),
                "format": _audio_format(path),
            },
        }
        if language:
            body["language"] = language
        return {"url": url, "headers": headers, "json": body, "timeout": 60.0}

    return await _post_with_retry(build_request, provider_label, _text_from_transcription_payload)


async def _post_xiaomi_mimo_asr_with_retry(
    url: str,
    *,
    api_key: str | None,
    path: Path,
    model: str,
    provider_label: str,
    language: str | None = None,
) -> str:
    """POST audio to Xiaomi MiMo ASR's chat-completions transcription API."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.exception("{} transcription error: cannot read audio file: {}", provider_label, e)
        return ""

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": (
                                f"data:{_audio_mime_type(path)};base64,"
                                f"{base64.b64encode(data).decode('ascii')}"
                            ),
                        },
                    }
                ],
            }
        ],
    }
    if language:
        body["asr_options"] = {"language": language}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def build_request() -> dict[str, Any]:
        return {"url": url, "headers": headers, "json": body, "timeout": 60.0}

    return await _post_with_retry(build_request, provider_label, _text_from_chat_payload)


async def _post_stepfun_asr_with_retry(
    url: str,
    *,
    api_key: str | None,
    path: Path,
    model: str,
    provider_label: str,
    language: str | None = None,
) -> str:
    """POST audio to StepFun ASR SSE endpoint and collect final text."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.exception("{} transcription error: cannot read audio file: {}", provider_label, e)
        return ""

    suffix = path.suffix.lstrip(".").lower()
    audio_type = suffix if suffix in ("ogg", "mp3", "wav", "pcm") else "wav"

    body: dict[str, Any] = {
        "audio": {
            "data": base64.b64encode(data).decode("ascii"),
            "input": {
                "transcription": {
                    "model": model,
                    "enable_itn": True,
                },
                "format": {"type": audio_type},
            },
        },
    }
    if language:
        body["audio"]["input"]["transcription"]["language"] = language

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    async with httpx.AsyncClient() as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with client.stream(
                    "POST", url, headers=headers, json=body, timeout=60.0
                ) as resp:
                    if resp.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                        logger.warning(
                            "{} transcription transient HTTP {} (attempt {}/{})",
                            provider_label,
                            resp.status_code,
                            attempt + 1,
                            _MAX_RETRIES + 1,
                        )
                        await asyncio.sleep(_BACKOFF_S[attempt])
                        continue
                    resp.raise_for_status()
                    final_text = None
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload_str = line[len("data:") :].strip()
                        if not payload_str:
                            continue
                        try:
                            payload = json.loads(payload_str)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        event_type = payload.get("type", "")
                        if event_type == "error":
                            msg = payload.get("message", "unknown error")
                            logger.error("{} ASR error: {}", provider_label, msg)
                            return ""
                        if event_type == "transcript.text.done":
                            final_text = payload.get("text", "")
                            break
                    if final_text is not None:
                        return final_text
                    # Stream ended without a final event — retry if attempts remain
                    if attempt < _MAX_RETRIES:
                        logger.warning(
                            "{} transcription: no final event (attempt {}/{})",
                            provider_label,
                            attempt + 1,
                            _MAX_RETRIES + 1,
                        )
                        await asyncio.sleep(_BACKOFF_S[attempt])
                        continue
                    logger.error(
                        "{} transcription: stream ended without final text after {} attempts",
                        provider_label,
                        _MAX_RETRIES + 1,
                    )
                    return ""
            except httpx.HTTPStatusError:
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_BACKOFF_S[attempt])
                    continue
                logger.exception(
                    "{} transcription failed after {} attempts",
                    provider_label,
                    _MAX_RETRIES + 1,
                )
                return ""
            except (httpx.RequestError, Exception):
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_BACKOFF_S[attempt])
                    continue
                logger.exception("{} transcription request error", provider_label)
                return ""
    return ""


async def _post_with_retry(
    build_request: Callable[[], dict[str, Any]],
    provider_label: str,
    extract_text: Callable[[dict[str, Any]], str],
) -> str:
    async with httpx.AsyncClient() as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await client.post(**build_request())
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
            except httpx.HTTPStatusError:
                body = response.text.strip().replace("\n", " ")[:500]
                logger.error(
                    "{} transcription HTTP {}{}{}",
                    provider_label,
                    response.status_code,
                    f" {response.reason_phrase}" if response.reason_phrase else "",
                    f": {body}" if body else "",
                )
                return ""
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
            return extract_text(payload)
    return ""


def _text_from_transcription_payload(payload: dict[str, Any]) -> str:
    text = payload.get("text")
    return text if isinstance(text, str) else ""


def _text_from_chat_payload(payload: dict[str, Any]) -> str:
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""
    return text if isinstance(text, str) else ""


def _assemblyai_speech_models(model: str | None) -> list[str]:
    return [part for part in (part.strip() for part in (model or "").split(",")) if part]


class AssemblyAITranscriptionProvider:
    """Voice transcription provider using AssemblyAI's asynchronous REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ):
        base = api_base or os.environ.get("ASSEMBLYAI_BASE_URL")
        self.api_key = api_key or os.environ.get("ASSEMBLYAI_API_KEY")
        self.upload_url = _resolve_api_path(base, _ASSEMBLYAI_DEFAULT_API_BASE, "upload")
        self.transcript_url = _resolve_api_path(base, _ASSEMBLYAI_DEFAULT_API_BASE, "transcript")
        self.language = language or None
        self.model = model or "universal-3-pro,universal-2"
        logger.debug("AssemblyAI transcription endpoint: {}", self.transcript_url)

    async def transcribe(self, file_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("AssemblyAI API key not configured for transcription")
            return ""
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""
        try:
            data = path.read_bytes()
        except OSError as e:
            logger.exception("AssemblyAI transcription error: cannot read audio file: {}", e)
            return ""

        headers = {"Authorization": self.api_key}
        async with httpx.AsyncClient() as client:
            upload = await _request_json_with_retry(
                client,
                "POST",
                self.upload_url,
                provider_label="AssemblyAI",
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=data,
                timeout=60.0,
            )
            upload_url = upload.get("upload_url") if upload else None
            if not isinstance(upload_url, str) or not upload_url:
                logger.error("AssemblyAI transcription error: upload_url missing")
                return ""

            body: dict[str, object] = {"audio_url": upload_url}
            speech_models = _assemblyai_speech_models(self.model)
            if speech_models:
                body["speech_models"] = speech_models
            if self.language:
                body["language_code"] = self.language

            transcript = await _request_json_with_retry(
                client,
                "POST",
                self.transcript_url,
                provider_label="AssemblyAI",
                headers=headers,
                json=body,
                timeout=30.0,
            )
            transcript_id = transcript.get("id") if transcript else None
            if not isinstance(transcript_id, str) or not transcript_id:
                logger.error("AssemblyAI transcription error: transcript id missing")
                return ""

            poll_url = f"{self.transcript_url.rstrip('/')}/{transcript_id}"
            for attempt in range(_ASSEMBLYAI_POLL_ATTEMPTS):
                payload = await _request_json_with_retry(
                    client,
                    "GET",
                    poll_url,
                    provider_label="AssemblyAI",
                    headers=headers,
                    timeout=30.0,
                )
                if not payload:
                    return ""
                status = str(payload.get("status") or "").lower()
                if status == "completed":
                    text = payload.get("text")
                    return text if isinstance(text, str) else ""
                if status in {"error", "failed"}:
                    logger.error(
                        "AssemblyAI transcription failed: {}",
                        payload.get("error") or payload,
                    )
                    return ""
                if attempt < _ASSEMBLYAI_POLL_ATTEMPTS - 1:
                    await asyncio.sleep(_ASSEMBLYAI_POLL_INTERVAL_S)
            logger.error("AssemblyAI transcription timed out while polling transcript")
            return ""


class OpenAITranscriptionProvider:
    """Voice transcription provider using OpenAI's Whisper API."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.api_url = _resolve_transcription_url(
            api_base or os.environ.get("OPENAI_TRANSCRIPTION_BASE_URL"),
            "https://api.openai.com/v1/audio/transcriptions",
        )
        self.language = language or None
        self.model = model or "whisper-1"
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
            model=self.model,
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
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = _resolve_transcription_url(
            api_base or os.environ.get("GROQ_BASE_URL"),
            "https://api.groq.com/openai/v1/audio/transcriptions",
        )
        self.language = language or None
        self.model = model or "whisper-large-v3"
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
            model=self.model,
            provider_label="Groq",
            language=self.language,
        )


class OpenRouterTranscriptionProvider:
    """Voice transcription provider using OpenRouter's speech-to-text endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.api_url = _resolve_transcription_url(
            api_base or os.environ.get("OPENROUTER_BASE_URL"),
            "https://openrouter.ai/api/v1/audio/transcriptions",
        )
        self.language = language or None
        self.model = model or "openai/whisper-1"
        logger.debug("OpenRouter transcription endpoint: {}", self.api_url)

    async def transcribe(self, file_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("OpenRouter API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        return await _post_json_transcription_with_retry(
            self.api_url,
            api_key=self.api_key,
            path=path,
            model=self.model,
            provider_label="OpenRouter",
            language=self.language,
        )


class XiaomiMiMoTranscriptionProvider:
    """Voice transcription provider using Xiaomi MiMo ASR."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("MIMO_API_KEY")
        self.api_url = _resolve_chat_completions_url(
            api_base or os.environ.get("MIMO_API_BASE"),
            "https://api.xiaomimimo.com/v1/chat/completions",
        )
        self.language = language or None
        self.model = model or "mimo-v2.5-asr"
        logger.debug("Xiaomi MiMo transcription endpoint: {}", self.api_url)

    async def transcribe(self, file_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("Xiaomi MiMo API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        return await _post_xiaomi_mimo_asr_with_retry(
            self.api_url,
            api_key=self.api_key,
            path=path,
            model=self.model,
            provider_label="Xiaomi MiMo",
            language=self.language,
        )


class StepFunTranscriptionProvider:
    """Voice transcription provider using StepFun ASR SSE endpoint."""

    _DEFAULT_URL = "https://api.stepfun.com/v1/audio/asr/sse"

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        language: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("STEPFUN_API_KEY")
        # api_base is used verbatim; users can point to the Plan endpoint
        # (https://api.stepfun.com/step_plan/v1/audio/asr/sse) or any
        # compatible proxy.
        self.api_url = api_base or self._DEFAULT_URL
        self.language = language or None
        self.model = model or "stepaudio-2.5-asr"
        logger.debug("StepFun transcription endpoint: {}", self.api_url)

    async def transcribe(self, file_path: str | Path) -> str:
        if not self.api_key:
            logger.warning("StepFun API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        return await _post_stepfun_asr_with_retry(
            self.api_url,
            api_key=self.api_key,
            path=path,
            model=self.model,
            provider_label="StepFun",
            language=self.language,
        )
