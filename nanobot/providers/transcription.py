"""Voice transcription providers (Groq, OpenAI Whisper, and local faster-whisper)."""

import asyncio
import os
import time
from pathlib import Path

import httpx
from loguru import logger

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
        self.api_url = (
            api_base
            or os.environ.get("OPENAI_TRANSCRIPTION_BASE_URL")
            or "https://api.openai.com/v1/audio/transcriptions"
        )
        self.language = language or None

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
        self.api_url = (
            api_base
            or os.environ.get("GROQ_BASE_URL")
            or "https://api.groq.com/openai/v1/audio/transcriptions"
        )
        self.language = language or None

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


_MODEL_TTL = 600  # seconds of inactivity before unloading cached faster-whisper model


class FasterWhisperTranscriptionProvider:
    """Voice transcription using faster-whisper locally.

    Uses the C++/ONNX implementation of Whisper for fast local inference.
    No API key or network access required — runs entirely on the host machine.

    Args:
        model_size: One of ``tiny``, ``base``, ``small``, ``medium``, ``large-v3``.
            Defaults to ``small`` (good quality/speed/RAM trade-off).
        device: ``cpu`` or ``cuda``.  Defaults to ``auto`` which picks
            ``cuda`` if a CUDA-capable GPU is detected, otherwise ``cpu``.
        language: Optional ISO-639-1/2 language hint (e.g. ``"it"``, ``"en"``).
    """

    _model = None  # cached across instances — WhisperModel init is expensive
    _last_used = 0.0
    _lock = None
    _unload_handle = None

    @classmethod
    def _schedule_unload(cls):
        if cls._unload_handle is not None:
            cls._unload_handle.cancel()
        loop = asyncio.get_running_loop()
        cls._unload_handle = loop.call_later(_MODEL_TTL, cls._do_unload)

    @classmethod
    def _do_unload(cls):
        logger.info("Unloading faster-whisper model (idle TTL)")
        cls._model = None
        cls._unload_handle = None

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        language: str | None = None,
    ):
        self._model_size = model_size
        self._device = device
        self.language = language or None

    @property
    def _effective_device(self) -> str:
        if self._device != "auto":
            return self._device
        # Simple autodetect: try importing torch to check for CUDA.
        # If torch is not available, fall back to cpu (faster-whisper works on cpu too).
        try:
            import torch  # type: ignore[import-not-found]
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    async def transcribe(self, file_path: str | Path) -> str:
        if FasterWhisperTranscriptionProvider._lock is None:
            FasterWhisperTranscriptionProvider._lock = asyncio.Lock()

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        async with FasterWhisperTranscriptionProvider._lock:
            FasterWhisperTranscriptionProvider._last_used = time.monotonic()

            try:
                from faster_whisper import WhisperModel  # type: ignore[import-not-found]
            except ImportError as exc:
                logger.error(
                    "faster-whisper is not installed. Install it with: pip install faster-whisper"
                )
                return ""

            loop = asyncio.get_running_loop()

            # Load model only if not already cached
            if FasterWhisperTranscriptionProvider._model is None:
                def _load_model():
                    device = self._effective_device
                    logger.info(
                        "Loading faster-whisper model '{}' on device '{}' (first use, may download)",
                        self._model_size,
                        device,
                    )
                    return WhisperModel(self._model_size, device=device)

                model = await loop.run_in_executor(None, _load_model)
                FasterWhisperTranscriptionProvider._model = model
            else:
                model = FasterWhisperTranscriptionProvider._model

            def _transcribe(model):
                segments, info = model.transcribe(
                    str(path),
                    language=self.language,
                    beam_size=1,
                )
                logger.info(
                    "Transcribed {} (lang={}): detected language={}, duration={:.0f}s",
                    path.name,
                    self.language or "auto",
                    info.language,
                    info.duration,
                )
                return " ".join(seg.text for seg in segments)

            try:
                text = await loop.run_in_executor(None, _transcribe, model)
                return text or ""
            except Exception as exc:
                logger.exception("faster-whisper transcription error: {}", exc)
                return ""
            finally:
                FasterWhisperTranscriptionProvider._schedule_unload()
