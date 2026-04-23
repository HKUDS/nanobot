"""Tests for OpenAI-compatible embeddings support."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import EmbeddingResponse
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


class _MockEmbeddingResult:
    def __init__(self, embeddings: list[list[float]], model: str, usage: dict[str, int] | None = None):
        self._payload = {
            "data": [{"embedding": vector} for vector in embeddings],
            "model": model,
            "usage": usage or {"prompt_tokens": len(embeddings), "total_tokens": len(embeddings)},
        }

    def model_dump(self) -> dict[str, object]:
        return self._payload


@pytest.mark.asyncio
async def test_openai_compat_embed_truncates_dimensions_locally() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(api_key="test-key", default_model="embedding-model")

    provider._client.embeddings = MagicMock()
    provider._client.embeddings.create = AsyncMock(
        return_value=_MockEmbeddingResult(
            embeddings=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            model="embedding-model",
            usage={"prompt_tokens": 2, "total_tokens": 2},
        )
    )

    result = await provider.embed(["alpha", "beta"], dimensions=2)

    call_kwargs = provider._client.embeddings.create.call_args.kwargs
    assert call_kwargs == {"input": ["alpha", "beta"], "model": "embedding-model"}
    assert isinstance(result, EmbeddingResponse)
    assert result.embeddings == [[0.1, 0.2], [0.4, 0.5]]
    assert result.model == "embedding-model"


@pytest.mark.asyncio
async def test_azure_openai_embed_truncates_dimensions_locally() -> None:
    with patch("nanobot.providers.azure_openai_provider.AsyncOpenAI"):
        provider = AzureOpenAIProvider(
            api_key="test-key",
            api_base="https://example.openai.azure.com",
            default_model="embedding-deployment",
        )

    provider._client.embeddings = MagicMock()
    provider._client.embeddings.create = AsyncMock(
        return_value=_MockEmbeddingResult(
            embeddings=[[1.0, 2.0, 3.0]],
            model="embedding-deployment",
            usage={"prompt_tokens": 1, "total_tokens": 1},
        )
    )

    result = await provider.embed("hello", dimensions=1)

    call_kwargs = provider._client.embeddings.create.call_args.kwargs
    assert call_kwargs == {"input": "hello", "model": "embedding-deployment"}
    assert isinstance(result, EmbeddingResponse)
    assert result.embeddings == [[1.0]]
    assert result.model == "embedding-deployment"


@pytest.mark.asyncio
async def test_openai_compat_embed_returns_error_metadata_on_exception() -> None:
    with patch("nanobot.providers.openai_compat_provider.AsyncOpenAI"):
        provider = OpenAICompatProvider(api_key="test-key", default_model="embedding-model")

    error = RuntimeError("rate limited")
    error.status_code = 429
    error.response = SimpleNamespace(
        status_code=429,
        text='{"error": {"message": "rate limited", "type": "rate_limit_error", "code": "rate_limit_error"}}',
        headers={"retry-after": "2", "x-should-retry": "true"},
    )

    provider._client.embeddings = MagicMock()
    provider._client.embeddings.create = AsyncMock(side_effect=error)

    result = await provider.embed("hello")

    assert result.embeddings == []
    assert result.error_status_code == 429
    assert result.error_type == "rate_limit_error"
    assert result.error_code == "rate_limit_error"
    assert result.error_retry_after_s == 2.0
    assert result.error_should_retry is True
    assert "rate limited" in (result.content or "").lower()
