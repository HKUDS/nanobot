"""Voice transcription — LiteLLM for supported providers, AsyncOpenAI direct for others."""

from __future__ import annotations

from pathlib import Path

import litellm
from loguru import logger
from openai import AsyncOpenAI


class TranscriptionProvider:
    def __init__(self, *, use_litellm: bool, api_key: str, base_url: str | None, model: str):
        self._use_litellm = use_litellm
        self._api_key = api_key
        self._model = model
        if not use_litellm:
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def transcribe(self, file_path: str | Path) -> str:
        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""
        try:
            with open(path, "rb") as f:
                if self._use_litellm:
                    response = await litellm.atranscription(
                        model=self._model,
                        file=(path.name, f),
                        api_key=self._api_key,
                    )
                else:
                    response = await self._client.audio.transcriptions.create(
                        model=self._model,
                        file=(path.name, f),
                    )
            return response.text
        except Exception as e:
            logger.error("Transcription error: {}", e)
            return ""


def create_transcription_service(transcription_config, providers_config) -> TranscriptionProvider | None:
    """Create a TranscriptionProvider from explicit config. Returns None if not configured."""
    if transcription_config is None:
        return None

    provider_name = transcription_config.provider
    model = transcription_config.model

    if not provider_name and not model:
        return None  # not configured

    if not provider_name or not model:
        logger.warning("Transcription disabled: both provider and model must be set")
        return None

    provider_cfg = getattr(providers_config, provider_name, None)
    if provider_cfg is None:
        logger.warning("Transcription disabled: '{}' is not a known provider name", provider_name)
        return None

    api_key = provider_cfg.api_key
    if not api_key:
        logger.warning("Transcription disabled: providers.{}.api_key is not set", provider_name)
        return None

    from nanobot.providers.registry import find_by_name
    spec = find_by_name(provider_name)
    use_litellm = spec.supports_litellm_transcription if spec else False
    base_url = provider_cfg.api_base or (spec.default_api_base if spec else None) or None

    if not use_litellm and not base_url:
        logger.warning(
            "Transcription disabled: providers.{}.api_base is not set. "
            "Set it to the provider's transcription endpoint (e.g. https://api.mistral.ai/v1).",
            provider_name,
        )
        return None

    return TranscriptionProvider(
        use_litellm=use_litellm,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
