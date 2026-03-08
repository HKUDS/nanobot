"""Voice transcription providers using LiteLLM and local backends."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from functools import partial
from pathlib import Path
from typing import Any

from litellm import atranscription
from loguru import logger

from nanobot.config.schema import TranscriptionConfig


class TranscriptionProvider(ABC):
    """Base class for transcription providers."""

    @abstractmethod
    async def transcribe(self, file_path: str | Path) -> str:
        """Transcribe an audio file and return the text."""
        pass

    async def preload(self) -> None:
        """Optional: eagerly load model weights into memory before first use."""
        pass


class LiteLLMTranscriptionProvider(TranscriptionProvider):
    """
    Cloud/remote transcription via LiteLLM.
    Supports Groq, OpenAI, and any other LiteLLM-compatible endpoint.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base

    async def transcribe(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        kwargs: dict[str, Any] = {"model": self.model, "file": open(path, "rb")}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        try:
            response = await atranscription(**kwargs)
            return response.get("text", "")
        except Exception as e:
            logger.error("LiteLLM transcription error: {}", e)
            return ""
        finally:
            kwargs["file"].close()


class MLXTranscriptionProvider(TranscriptionProvider):
    """
    Local transcription using mlx-whisper, optimised for Apple Silicon.

    The model is loaded lazily on first use. If `preload=True`, it is instead
    loaded eagerly in the background (via `preload()`) so the first real
    transcription is instantaneous.
    """

    def __init__(self, model: str = "mlx-community/whisper-large-v3-mlx", preload: bool = False):
        self.model = model
        self._do_preload = preload
        self._preload_task: asyncio.Task | None = None

        try:
            import mlx_whisper
            self._mlx = mlx_whisper
        except ImportError:
            self._mlx = None
            logger.warning("mlx-whisper not installed. Run: pip install mlx-whisper")

    async def preload(self) -> None:
        """Start loading the model into memory in a background task."""
        if not self._do_preload or not self._mlx or self._preload_task:
            return
        logger.info("MLX: preloading model in background: {}", self.model)
        self._preload_task = asyncio.create_task(self._load_model())

    async def _load_model(self) -> None:
        """Load model weights through ModelHolder so transcribe() reuses the cache."""
        try:
            import mlx.core as mx
            from mlx_whisper.transcribe import ModelHolder

            await asyncio.get_event_loop().run_in_executor(
                None, partial(ModelHolder.get_model, self.model, mx.float16)
            )
            logger.info("MLX: model resident in memory: {}", self.model)
        except Exception as e:
            logger.warning("MLX: preload failed: {}", e)

    async def transcribe(self, file_path: str | Path) -> str:
        if not self._mlx:
            return ""

        # If preloading is in-flight, finish that first — no double load
        if self._preload_task and not self._preload_task.done():
            await self._preload_task

        path = str(Path(file_path).absolute())
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, partial(self._mlx.transcribe, path, path_or_hf_repo=self.model)
            )
            return result.get("text", "").strip()
        except Exception as e:
            logger.error("MLX transcription error: {}", e)
            return ""


def get_transcription_provider(config: TranscriptionConfig | None) -> TranscriptionProvider | None:
    """Factory: create the right transcription provider from config."""
    if not config or not config.enabled:
        return None

    p = config.provider.lower()

    if p == "mlx":
        return MLXTranscriptionProvider(model=config.model, preload=config.preload)

    # Everything else goes through LiteLLM (groq, openai, azure, deepgram, …)
    model = config.model
    if "/" not in model and p not in ("openai", "custom"):
        model = f"{p}/{model}"

    return LiteLLMTranscriptionProvider(
        model=model,
        api_key=config.api_key or None,
        api_base=config.api_base,
    )
