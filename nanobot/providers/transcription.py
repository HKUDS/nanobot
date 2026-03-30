"""Voice transcription providers."""

import asyncio
import base64
import os
from pathlib import Path

import httpx
from loguru import logger


class GroqTranscriptionProvider:
    """
    Voice transcription provider using Groq's Whisper API.

    Groq offers extremely fast transcription with a generous free tier.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"

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

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f),
                        "model": (None, "whisper-large-v3"),
                    }
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


class Qwen3ASRTranscriptionProvider:
    """
    Voice transcription provider using Alibaba Cloud Qwen3-ASR-Flash.

    LLM-based ASR with superior Chinese/dialect support. Sync call, no polling.
    Requires: pip install dashscope
    API key: https://dashscope.console.aliyun.com/
    """

    MODEL = "qwen3-asr-flash"
    # Audio MIME types for base64 data URL
    _MIME = {
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
        ".opus": "audio/opus", ".m4a": "audio/mp4", ".flac": "audio/flac",
        ".aac": "audio/aac", ".amr": "audio/amr", ".webm": "audio/webm",
    }

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using Qwen3-ASR-Flash.

        Reads the local file, encodes as base64 data URL, calls MultiModalConversation
        synchronously (no polling required).

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text.
        """
        if not self.api_key:
            logger.warning("Qwen3-ASR API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            import dashscope
        except ImportError:
            logger.error("dashscope not installed. Run: pip install dashscope")
            return ""

        try:
            mime = self._MIME.get(path.suffix.lower(), "audio/mpeg")
            audio_data = base64.b64encode(path.read_bytes()).decode()
            data_url = f"data:{mime};base64,{audio_data}"

            response = await asyncio.to_thread(
                dashscope.MultiModalConversation.call,
                model=self.MODEL,
                api_key=self.api_key,
                messages=[{
                    "role": "user",
                    "content": [{"audio": data_url}],
                }],
            )

            if response.status_code != 200:
                logger.error("Qwen3-ASR failed: {} {}", response.status_code, response.message)
                return ""

            choices = getattr(response.output, "choices", None)
            if not choices:
                logger.error("Qwen3-ASR returned empty choices")
                return ""
            content = getattr(choices[0].message, "content", None)
            if not content:
                return ""
            return content[0].get("text", "") if isinstance(content[0], dict) else ""

        except Exception as e:
            logger.error("Qwen3-ASR transcription error: {}", e)
            return ""
