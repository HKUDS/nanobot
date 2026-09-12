from __future__ import annotations

import os
import uuid

import pytest

from nanobot.semantic_memory.models import MemoryRecord
from nanobot.semantic_memory.postgres import PostgresSemanticMemoryRepository


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("NANOBOT_TEST_POSTGRES_DSN"),
    reason="NANOBOT_TEST_POSTGRES_DSN is not configured",
)
async def test_postgres_upsert_vector_fts_and_namespace_isolation() -> None:
    dsn = os.environ["NANOBOT_TEST_POSTGRES_DSN"]
    namespace = f"test-{uuid.uuid4().hex}"
    other_namespace = f"test-{uuid.uuid4().hex}"
    repository = PostgresSemanticMemoryRepository(
        dsn,
        model_id="integration-test-384",
        dimension=384,
    )
    vector = [0.0] * 384
    vector[0] = 1.0
    try:
        await repository.upsert(namespace, [MemoryRecord(
            source_type="history",
            source_key="cursor:1:chunk:0",
            content="Szymon wybrał PostgreSQL jako bazę pamięci wektorowej.",
            content_hash="hash-one",
            embedding=vector,
            session_key="websocket:test",
        )])
        await repository.upsert(other_namespace, [MemoryRecord(
            source_type="history",
            source_key="cursor:1:chunk:0",
            content="Ten rekord nie może przeciec między przestrzeniami.",
            content_hash="hash-two",
            embedding=vector,
            session_key="websocket:test",
        )])
        await repository.upsert(namespace, [
            MemoryRecord(
                source_type="history",
                source_key="cursor:legacy:chunk:0",
                content="Legacy history without a session must not leak.",
                content_hash="hash-legacy",
                embedding=vector,
                session_key=None,
            ),
            MemoryRecord(
                source_type="memory",
                source_key="MEMORY.md:chunk:0",
                content="Global durable memory is available in every session.",
                content_hash="hash-global",
                embedding=vector,
                session_key=None,
            ),
        ])
        hits = await repository.hybrid_search(
            namespace,
            query="PostgreSQL pamięć wektorowa",
            embedding=vector,
            session_key="websocket:test",
            scope="session",
            candidate_k=10,
            top_k=5,
            min_score=0,
            min_vector_similarity=0.2,
        )
        assert len(hits) == 2
        contents = [hit.content for hit in hits]
        assert any("PostgreSQL" in content for content in contents)
        assert any("Global durable" in content for content in contents)
        assert all("Legacy history" not in content for content in contents)
        assert all("przeciec" not in content for content in contents)

        # Repeating an identical source key updates rather than duplicates.
        await repository.upsert(namespace, [MemoryRecord(
            source_type="history",
            source_key="cursor:1:chunk:0",
            content="Szymon wybrał PostgreSQL i pgvector.",
            content_hash="hash-three",
            embedding=vector,
            session_key="websocket:test",
        )])
        assert (await repository.status(namespace))["items"] == 3
    finally:
        await repository.purge(namespace)
        await repository.purge(other_namespace)
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("NANOBOT_TEST_POSTGRES_DSN"),
    reason="NANOBOT_TEST_POSTGRES_DSN is not configured",
)
async def test_purge_allows_rebuild_with_a_different_model() -> None:
    dsn = os.environ["NANOBOT_TEST_POSTGRES_DSN"]
    namespace = f"test-rebuild-{uuid.uuid4().hex}"
    vector = [0.0] * 384
    original = PostgresSemanticMemoryRepository(
        dsn,
        model_id="integration-model-before",
        dimension=384,
    )
    replacement = PostgresSemanticMemoryRepository(
        dsn,
        model_id="integration-model-after",
        dimension=384,
    )
    try:
        await original.upsert(namespace, [MemoryRecord(
            source_type="memory",
            source_key="MEMORY.md:chunk:0",
            content="before rebuild",
            content_hash="before",
            embedding=vector,
        )])
        assert await original.purge(namespace) == 1
        await replacement.upsert(namespace, [MemoryRecord(
            source_type="memory",
            source_key="MEMORY.md:chunk:0",
            content="after rebuild",
            content_hash="after",
            embedding=vector,
        )])
        assert (await replacement.status(namespace))["items"] == 1
    finally:
        await replacement.purge(namespace)
        await original.close()
        await replacement.close()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("NANOBOT_TEST_POSTGRES_DSN"),
    reason="NANOBOT_TEST_POSTGRES_DSN is not configured",
)
async def test_forget_deletes_duplicates_and_preserves_all_forgotten_hashes() -> None:
    dsn = os.environ["NANOBOT_TEST_POSTGRES_DSN"]
    namespace = f"test-forget-{uuid.uuid4().hex}"
    repository = PostgresSemanticMemoryRepository(
        dsn,
        model_id="integration-forget-384",
        dimension=384,
    )
    vector = [0.0] * 384
    try:
        await repository.upsert(namespace, [
            MemoryRecord(
                source_type="memory",
                source_key="MEMORY.md:chunk:0",
                content="forgotten secret",
                content_hash="secret-hash",
                embedding=vector,
            ),
            MemoryRecord(
                source_type="memory",
                source_key="MEMORY.md:chunk:1",
                content="forgotten secret",
                content_hash="secret-hash",
                embedding=vector,
            ),
        ])
        assert await repository.forget(
            namespace, "memory", "MEMORY.md:chunk:0"
        ) == 2

        await repository.upsert(namespace, [MemoryRecord(
            source_type="memory",
            source_key="MEMORY.md:chunk:0",
            content="a different fact at the old position",
            content_hash="new-hash",
            embedding=vector,
        )])
        assert await repository.forget(
            namespace, "memory", "MEMORY.md:chunk:0"
        ) == 1

        legacy_keys, hashes = await repository.tombstoned_entries(namespace)
        assert legacy_keys == set()
        assert hashes == {"secret-hash", "new-hash"}
        assert (await repository.status(namespace))["items"] == 0
    finally:
        await repository.purge(namespace)
        await repository.close()
