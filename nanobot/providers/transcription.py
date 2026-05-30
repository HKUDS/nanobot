"""Voice transcription providers (Groq, OpenAI Whisper, and FunASR)."""

import asyncio
import io
import os
import shutil
from pathlib import Path

import httpx
from loguru import logger

from nanobot.utils.media_decode import webm_to_wav

_TRANSCRIPTIONS_PATH = "audio/transcriptions"


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


class FunAsrProvider:
    """
    Voice transcription provider using local FunASR model.

    FunASR provides offline speech recognition with support for multiple languages.
    Requires: pip install funasr psutil torch torchaudio
    """

    def __init__(
        self,
        model: str | None = None,
        language: str | None = None,
    ):
        """
        Initialize FunASR transcription provider.

        Args:
            model: Path to FunASR model directory or model name (default: "paraformer-zh")
            language: Language hint for transcription (default: "auto")
        """
        self.model = model or "paraformer-zh"
        self.language = language or "auto"
        self._model_instance = None

        try:
            import psutil
            import torch
            import torchaudio
            from funasr import AutoModel
        except ImportError:
            logger.error(
                "FunAsrProvider initialization failed. Install with: pip install funasr psutil torch torchaudio"
            )
            return

        # Memory check - require at least 2GB
        min_mem_bytes = 2 * 1024 * 1024 * 1024
        total_mem = psutil.virtual_memory().total
        if total_mem < min_mem_bytes:
            logger.error(
                f"Insufficient memory (less than 2GB), only {total_mem / (1024 * 1024):.2f} MB available, FunASR may fail to start"
            )

        # Handle local model path
        model_path, local_dir = Path(self.model).expanduser(), None
        if model_path.is_dir():
            model_str = str(model_path)
            # FunASR bug: model path should start with "models"
            if model_str.startswith("models"):
                logger.debug(f"Load local ASR model {model_str}")
            else:
                local_dir = Path("models")
                local_dir.mkdir(parents=True, exist_ok=True)
                dst_model = local_dir / model_path.name
                logger.debug(f"Copy local ASR model to {dst_model} from {model_path}")
                if model_path.is_dir() and not dst_model.exists():
                    shutil.copytree(model_path, dst_model)
                model_str = str(dst_model)
        else:
            logger.debug(f"Load remote ASR model {self.model}")
            model_str = self.model

        # Load FunASR model
        try:
            self._model_instance = AutoModel(
                model=model_str,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                hub="hf",
                disable_update=True,
            )
            logger.debug("FunASR model loaded successfully")
        except Exception as e:
            logger.exception("Failed to load FunASR model: {}", e)

        # Clean up temporary directory
        if local_dir and local_dir.exists():
            shutil.rmtree(local_dir)

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using FunASR.

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text.
        """
        if self._model_instance is None:
            logger.error("FunASR model not initialized")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        # Convert webm to wav if needed
        if path.suffix.lower() == ".webm":
            audio_bytes = webm_to_wav(input_file=path)
        else:
            audio_bytes = path.read_bytes()

        # Perform transcription
        result = self._model_instance.generate(
            input=audio_bytes,
            cache={},
            language=self.language,
            use_itn=True,
            batch_size_s=60,
        )
        if result and len(result) > 0:
            text = result[0].get("text", "")
            logger.debug("FunASR transcription result: {}", text)
            return text
        logger.warning("FunASR returned empty result")
        return ""
