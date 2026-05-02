"""Voice transcription providers (Groq and OpenAI Whisper)."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx
from loguru import logger


def _ensure_whisper_compatible_audio(path: Path) -> tuple[Path, str | None]:
    """Convert non-WAV input to 16 kHz mono WAV via ffmpeg.

    Cloud Whisper backends (OpenAI, Groq) accept many audio formats, but
    self-hosted ones — notably whisper.cpp's ``/inference`` endpoint —
    accept only 16 kHz mono WAV and reject everything else with HTTP 400.
    Telegram, WhatsApp and Feishu all deliver voice messages as OGG/Opus,
    which makes any local-Whisper deployment unusable without a separate
    pre-processing step.

    The function is best-effort: if ffmpeg is missing or the conversion
    fails, the original path is returned and the caller can still try the
    upload (cloud backends will succeed; local backends will keep their
    current 400 behaviour, which is no worse than today).

    Returns:
        ``(path_to_send, cleanup_path)``. ``cleanup_path`` is the absolute
        path of a tempfile that the caller should ``os.unlink`` once done,
        or ``None`` when no tempfile was created.
    """
    if path.suffix.lower() == ".wav":
        return path, None
    if not shutil.which("ffmpeg"):
        logger.warning(
            "ffmpeg not found on PATH; sending {} as-is. Local Whisper backends "
            "(whisper.cpp, etc.) require 16 kHz mono WAV and may reject this.",
            path.suffix,
        )
        return path, None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(path),
                "-ar", "16000", "-ac", "1", "-f", "wav",
                tmp.name,
            ],
            check=True, capture_output=True,
        )
        return Path(tmp.name), tmp.name
    except (subprocess.CalledProcessError, OSError) as e:
        stderr = ""
        if isinstance(e, subprocess.CalledProcessError) and e.stderr:
            stderr = e.stderr.decode(errors="ignore")[:200]
        logger.warning(
            "ffmpeg conversion of {} failed ({}); sending original. {}",
            path.name, type(e).__name__, stderr,
        )
        return path, None


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
        upload_path, cleanup_path = _ensure_whisper_compatible_audio(path)
        try:
            async with httpx.AsyncClient() as client:
                with open(upload_path, "rb") as f:
                    files = {"file": (upload_path.name, f), "model": (None, "whisper-1")}
                    if self.language:
                        files["language"] = (None, self.language)
                    headers = {"Authorization": f"Bearer {self.api_key}"}
                    response = await client.post(
                        self.api_url, headers=headers, files=files, timeout=60.0,
                    )
                    response.raise_for_status()
                    return response.json().get("text", "")
        except Exception as e:
            logger.error("OpenAI transcription error: {}", e)
            return ""
        finally:
            if cleanup_path:
                try:
                    os.unlink(cleanup_path)
                except OSError:
                    pass


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
        self.api_url = api_base or os.environ.get("GROQ_BASE_URL") or "https://api.groq.com/openai/v1/audio/transcriptions"
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

        upload_path, cleanup_path = _ensure_whisper_compatible_audio(path)
        try:
            async with httpx.AsyncClient() as client:
                with open(upload_path, "rb") as f:
                    files = {
                        "file": (upload_path.name, f),
                        "model": (None, "whisper-large-v3"),
                    }
                    if self.language:
                        files["language"] = (None, self.language)
                    headers = {
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        timeout=60.0
                    )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")

        except Exception as e:
            logger.error("Groq transcription error: {}", e)
            return ""
        finally:
            if cleanup_path:
                try:
                    os.unlink(cleanup_path)
                except OSError:
                    pass
