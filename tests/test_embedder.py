"""Tests for Embedder protocol and embedder implementations."""

from __future__ import annotations

import math

from nanobot.memory.embedder import HashEmbedder, LocalEmbedder


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

    async def test_embed_batch_empty_list(self):
        e = LocalEmbedder()
        results = await e.embed_batch([])
        assert results == []

    async def test_similar_texts_have_higher_cosine(self):
        """Semantic quality test — only works with real ONNX embeddings."""
        e = LocalEmbedder()
        v1 = await e.embed("I love coffee")
        v2 = await e.embed("I enjoy drinking coffee")
        v3 = await e.embed("quantum mechanics research paper")

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0.0

        sim_similar = cosine(v1, v2)
        sim_different = cosine(v1, v3)
        assert sim_similar > sim_different


class TestHashEmbedder:
    def test_available_is_true(self):
        e = HashEmbedder(dims=384)
        assert e.available is True

    def test_dims_matches_constructor(self):
        e = HashEmbedder(dims=128)
        assert e.dims == 128

    async def test_embed_returns_correct_length(self):
        e = HashEmbedder(dims=384)
        result = await e.embed("hello")
        assert len(result) == 384

    async def test_embed_is_deterministic(self):
        e = HashEmbedder(dims=384)
        v1 = await e.embed("hello")
        v2 = await e.embed("hello")
        assert v1 == v2

    async def test_different_texts_produce_different_vectors(self):
        e = HashEmbedder(dims=384)
        v1 = await e.embed("hello")
        v2 = await e.embed("world")
        assert v1 != v2

    async def test_vectors_are_unit_normalized(self):
        e = HashEmbedder(dims=384)
        v = await e.embed("test")
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 0.001

    async def test_embed_batch(self):
        e = HashEmbedder(dims=4)
        results = await e.embed_batch(["a", "b"])
        assert len(results) == 2
        assert len(results[0]) == 4

    async def test_works_with_sqlite_vec(self, tmp_path):
        """HashEmbedder vectors work with MemoryDatabase KNN search."""
        from nanobot.memory.db import MemoryDatabase

        e = HashEmbedder(dims=4)
        db = MemoryDatabase(tmp_path / "test.db", dims=4)
        v1 = await e.embed("coffee lover")
        db.event_store.insert_event(
            {
                "id": "e1",
                "type": "fact",
                "summary": "coffee lover",
                "timestamp": "2026-01-01",
                "created_at": "2026-01-01",
            },
            embedding=v1,
        )
        # Search with same text should find it
        query_vec = await e.embed("coffee lover")
        results = db.event_store.search_vector(query_vec, k=1)
        assert len(results) == 1
        assert results[0]["id"] == "e1"
        db.close()
