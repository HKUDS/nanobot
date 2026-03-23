"""Tests for Embedder protocol and LocalEmbedder implementation."""
from __future__ import annotations

from nanobot.agent.memory.embedder import LocalEmbedder


class TestLocalEmbedder:
    def test_available_is_true(self):
        e = LocalEmbedder()
        assert e.available is True

    def test_dims_is_384(self):
        e = LocalEmbedder()
        assert e.dims == 384

    async def test_embed_returns_list_of_floats(self):
        e = LocalEmbedder()
        result = await e.embed("hello world")
        assert isinstance(result, list)
        assert len(result) == 384
        assert all(isinstance(x, float) for x in result)

    async def test_embed_batch_returns_list_of_lists(self):
        e = LocalEmbedder()
        results = await e.embed_batch(["hello", "world"])
        assert len(results) == 2
        assert all(len(v) == 384 for v in results)

    async def test_embed_empty_string(self):
        e = LocalEmbedder()
        result = await e.embed("")
        assert len(result) == 384

    async def test_similar_texts_have_higher_cosine(self):
        e = LocalEmbedder()
        v1 = await e.embed("I love coffee")
        v2 = await e.embed("I enjoy drinking coffee")
        v3 = await e.embed("quantum mechanics research paper")
        # Cosine similarity: dot product of normalized vectors
        import math

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0.0

        sim_similar = cosine(v1, v2)
        sim_different = cosine(v1, v3)
        assert sim_similar > sim_different
