"""Tests for embedding search, cache, cosine similarity, and fallback."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from nanobot.agent.memory import MemoryStore
from nanobot.config.schema import MemoryConfig


def _make_store(workspace, threshold=5, model="test-embed", cache_max=2000):
    """Create a MemoryStore with custom config."""
    config = MemoryConfig(
        keyword_threshold=threshold,
        embedding_model=model,
        embedding_cache_max=cache_max,
    )
    return MemoryStore(workspace, memory_config=config)


def _make_vector(dim=8, seed=0.1):
    """Create a simple test vector."""
    return [seed * (i + 1) for i in range(dim)]


def _mock_embedding_response(vectors):
    """Create a mock litellm aembedding response."""
    resp = MagicMock()
    resp.data = [{"embedding": v} for v in vectors]
    return resp


# ============================================================================
# Cosine similarity
# ============================================================================


def test_cosine_similarity_identical():
    vec = [1.0, 2.0, 3.0]
    assert abs(MemoryStore._cosine_similarity(vec, vec) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert abs(MemoryStore._cosine_similarity(a, b)) < 1e-6


def test_cosine_similarity_zero_vector():
    a = [1.0, 2.0]
    b = [0.0, 0.0]
    assert MemoryStore._cosine_similarity(a, b) == 0.0


def test_cosine_similarity_opposite():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(MemoryStore._cosine_similarity(a, b) - (-1.0)) < 1e-6


# ============================================================================
# Embedding search
# ============================================================================


async def test_search_uses_keyword_below_threshold(memory_file):
    """When chunk count <= threshold, keyword search is used (no embedding call)."""
    store = _make_store(memory_file, threshold=100, model="test-embed")

    with patch("nanobot.agent.memory.MemoryStore._call_embedding") as mock_embed:
        results = await store.search("Python", max_results=3)
        mock_embed.assert_not_called()

    assert len(results) >= 1


async def test_search_uses_embedding_above_threshold(memory_file):
    """When chunk count > threshold and model configured, embedding search is used."""
    # threshold=1 so even a few chunks trigger embedding
    store = _make_store(memory_file, threshold=1, model="test-embed")

    chunks = store._build_chunks()
    num_chunks = len(chunks)
    # Vectors for all chunks + 1 for query
    chunk_vectors = [_make_vector(seed=0.1 * (i + 1)) for i in range(num_chunks)]
    query_vector = _make_vector(seed=0.5)

    call_count = 0

    async def fake_embed(texts):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return chunk_vectors[:len(texts)]
        return [query_vector]

    with patch.object(store, "_call_embedding", side_effect=fake_embed):
        results = await store.search("Python", max_results=3)

    assert call_count == 2  # once for chunks, once for query
    assert len(results) >= 1
    assert all(r.score > 0 for r in results)


async def test_embedding_search_fallback_on_error(memory_file):
    """If embedding fails, falls back to keyword search gracefully."""
    store = _make_store(memory_file, threshold=1, model="test-embed")

    async def failing_embed(texts):
        raise RuntimeError("API unavailable")

    with patch.object(store, "_call_embedding", side_effect=failing_embed):
        results = await store.search("Python", max_results=3)

    # Should still return results via keyword fallback
    assert len(results) >= 1
    assert "Python" in results[0].text


async def test_search_no_embedding_when_model_empty(memory_file):
    """When embedding_model is empty, always uses keyword even above threshold."""
    store = _make_store(memory_file, threshold=1, model="")

    with patch("nanobot.agent.memory.MemoryStore._call_embedding") as mock_embed:
        results = await store.search("Python", max_results=3)
        mock_embed.assert_not_called()


# ============================================================================
# Embedding cache
# ============================================================================


async def test_embedding_cache_hit(memory_file):
    """Second search with same content reuses cached embeddings."""
    store = _make_store(memory_file, threshold=1, model="test-embed")

    chunks = store._build_chunks()
    num_chunks = len(chunks)
    chunk_vectors = [_make_vector(seed=0.1 * (i + 1)) for i in range(num_chunks)]
    query_vector = _make_vector(seed=0.5)

    embed_calls = []

    async def tracking_embed(texts):
        embed_calls.append(len(texts))
        if len(texts) > 1:
            return chunk_vectors[:len(texts)]
        return [query_vector]

    with patch.object(store, "_call_embedding", side_effect=tracking_embed):
        await store.search("Python", max_results=3)
        first_calls = len(embed_calls)

        # Second search — chunks should be cached
        embed_calls.clear()
        await store.search("JavaScript", max_results=3)

    # Second search should only embed the query (1 text), not chunks again
    assert len(embed_calls) == 1
    assert embed_calls[0] == 1  # only the query


async def test_embedding_cache_invalidate_on_content_change(memory_file):
    """Modifying a memory entry causes only that chunk to be re-embedded."""
    store = _make_store(memory_file, threshold=1, model="test-embed")

    chunks = store._build_chunks()
    num_chunks = len(chunks)
    chunk_vectors = [_make_vector(seed=0.1 * (i + 1)) for i in range(num_chunks)]
    query_vector = _make_vector(seed=0.5)

    embed_calls = []

    async def tracking_embed(texts):
        embed_calls.append(texts)
        if len(texts) > 1:
            return chunk_vectors[:len(texts)]
        if len(texts) == 1 and texts[0].startswith("- "):
            return [_make_vector(seed=0.99)]
        return [query_vector]

    with patch.object(store, "_call_embedding", side_effect=tracking_embed):
        await store.search("test", max_results=3)
        embed_calls.clear()

        # Modify MEMORY.md — add a new entry
        mem_path = memory_file / "memory" / "MEMORY.md"
        content = mem_path.read_text()
        mem_path.write_text(content + "- [fact] New fact added\n")

        await store.search("test", max_results=3)

    # Should have 2 calls: one for the new chunk(s), one for query
    assert len(embed_calls) == 2
    # The chunk embed call should be small (just the new entry)
    chunk_call = embed_calls[0]
    assert len(chunk_call) == 1  # only the new chunk


async def test_embedding_cache_invalidate_on_model_change(memory_file):
    """Changing embedding model invalidates entire cache."""
    store1 = _make_store(memory_file, threshold=1, model="model-a")

    chunks = store1._build_chunks()
    num_chunks = len(chunks)

    async def fake_embed(texts):
        return [_make_vector(seed=0.1) for _ in texts]

    with patch.object(store1, "_call_embedding", side_effect=fake_embed):
        await store1.search("test", max_results=3)

    # Create new store with different model
    store2 = _make_store(memory_file, threshold=1, model="model-b")
    # Point to same cache dir
    store2._cache_path = store1._cache_path

    embed_calls = []

    async def tracking_embed(texts):
        embed_calls.append(len(texts))
        return [_make_vector(seed=0.2) for _ in texts]

    with patch.object(store2, "_call_embedding", side_effect=tracking_embed):
        await store2.search("test", max_results=3)

    # All chunks should be re-embedded (cache invalidated by model change)
    assert embed_calls[0] == num_chunks


async def test_embedding_cache_eviction(workspace):
    """Cache evicts oldest entries when exceeding max size."""
    (workspace / "memory" / "MEMORY.md").write_text(
        "# Memory\n\n## Notes\n" +
        "\n".join(f"- [fact] Fact {i}" for i in range(10)) + "\n"
    )
    store = _make_store(workspace, threshold=1, model="test-embed", cache_max=5)

    async def fake_embed(texts):
        return [_make_vector(seed=0.1 * i) for i, _ in enumerate(texts)]

    with patch.object(store, "_call_embedding", side_effect=fake_embed):
        await store.search("test", max_results=3)

    # Load cache and check size
    cache = store._load_embedding_cache()
    assert len(cache) <= 5
