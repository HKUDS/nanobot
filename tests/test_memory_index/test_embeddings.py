import asyncio

import httpx
import pytest

from nanobot.memory_index.embeddings import (
    EmbeddingUnavailableError,
    OllamaEmbeddingProvider,
)


def _mock_response(embedding: list[float]) -> httpx.Response:
    r = httpx.Response(200, json={"embedding": embedding})
    r._request = httpx.Request("POST", "http://localhost:11434/api/embeddings")
    return r


async def test_embed_batch_returns_vectors(monkeypatch):
    async def mock_post(self, url, **kw):
        return _mock_response([0.1, 0.2, 0.3])

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    provider = OllamaEmbeddingProvider(
        base_url="http://localhost:11434", model="nomic-embed-text", batch_size=16
    )
    result = await provider.embed_batch(["hello world", "foo bar"])
    assert len(result) == 2
    assert result[0] == pytest.approx([0.1, 0.2, 0.3])
    assert result[1] == pytest.approx([0.1, 0.2, 0.3])


async def test_embed_batch_raises_on_connection_error(monkeypatch):
    async def mock_post(self, url, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    provider = OllamaEmbeddingProvider(
        base_url="http://localhost:11434", model="nomic-embed-text", batch_size=16
    )
    with pytest.raises(EmbeddingUnavailableError):
        await provider.embed_batch(["hello"])


async def test_embed_batch_caches_results(monkeypatch):
    call_count = 0

    async def mock_post(self, url, **kw):
        nonlocal call_count
        call_count += 1
        return _mock_response([0.5, 0.5])

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    provider = OllamaEmbeddingProvider(
        base_url="http://localhost:11434", model="nomic-embed-text", batch_size=16
    )
    await provider.embed_batch(["same text"])
    await provider.embed_batch(["same text"])
    assert call_count == 1  # second call hits cache


async def test_embed_batch_respects_batch_size(monkeypatch):
    """3 texts with batch_size=2 should make exactly 3 individual API calls (Ollama API is per-text)."""
    calls = []

    async def mock_post(self, url, **kw):
        calls.append(kw.get("json", {}).get("prompt", ""))
        return _mock_response([0.1])

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    provider = OllamaEmbeddingProvider(
        base_url="http://localhost:11434", model="nomic-embed-text", batch_size=2
    )
    await provider.embed_batch(["a", "b", "c"])
    assert len(calls) == 3


async def test_embed_batch_concurrent_within_batch(monkeypatch):
    """batch_size=2 with 3 texts should fire 2 requests concurrently, then 1."""
    concurrent_at_peak = 0
    current_concurrent = 0

    async def mock_post(self, url, **kw):
        nonlocal concurrent_at_peak, current_concurrent
        current_concurrent += 1
        concurrent_at_peak = max(concurrent_at_peak, current_concurrent)
        await asyncio.sleep(0)  # yield to let other coroutines start
        current_concurrent -= 1
        return _mock_response([0.1])

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    provider = OllamaEmbeddingProvider(
        base_url="http://localhost:11434", model="nomic-embed-text", batch_size=2
    )
    result = await provider.embed_batch(["a", "b", "c"])
    assert len(result) == 3
    assert concurrent_at_peak == 2  # peak concurrency matches batch_size
