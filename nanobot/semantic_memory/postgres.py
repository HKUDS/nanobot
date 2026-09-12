"""Async PostgreSQL repository for hybrid vector and lexical recall."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nanobot.semantic_memory.models import MemoryRecord, SemanticHit


class PostgresSemanticMemoryRepository:
    def __init__(
        self,
        dsn: str,
        *,
        model_id: str,
        dimension: int,
        min_pool_size: int = 0,
        max_pool_size: int = 4,
    ) -> None:
        if dimension != 384:
            raise ValueError("the bundled schema currently requires 384-dimensional embeddings")
        self._dsn = dsn
        self._model_id = model_id
        self._dimension = dimension
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._pool: Any | None = None
        self._open_lock = asyncio.Lock()

    async def open(self) -> None:
        async with self._open_lock:
            if self._pool is not None:
                return
            try:
                from psycopg.rows import tuple_row
                from psycopg_pool import AsyncConnectionPool
            except ImportError as exc:  # pragma: no cover - environment-dependent
                raise RuntimeError(
                    "semantic memory requires psycopg[binary,pool]"
                ) from exc
            pool = AsyncConnectionPool(
                conninfo=self._dsn,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
                open=False,
                kwargs={"autocommit": True, "row_factory": tuple_row},
                timeout=5.0,
            )
            try:
                await pool.open(wait=True, timeout=10.0)
                self._pool = pool
                await self._ensure_schema()
            except BaseException:
                self._pool = None
                await pool.close()
                raise

    async def _ensure_schema(self) -> None:
        assert self._pool is not None
        sql_path = Path(__file__).with_name("sql") / "001_pgvector.sql"
        schema = sql_path.read_text(encoding="utf-8")
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(schema)
                await cur.execute(
                    "SELECT embedding_model, embedding_dimension "
                    "FROM nanobot_memory.collections WHERE workspace_namespace = %s",
                    ("__schema_contract__",),
                )
                row = await cur.fetchone()
                if row is None:
                    await cur.execute(
                        "INSERT INTO nanobot_memory.collections "
                        "(workspace_namespace, embedding_model, embedding_dimension) "
                        "VALUES (%s, %s, %s)",
                        ("__schema_contract__", self._model_id, self._dimension),
                    )
                elif int(row[1]) != self._dimension:
                    raise RuntimeError("semantic memory database embedding dimension mismatch")

    async def ensure_collection(self, namespace: str) -> None:
        await self.open()
        assert self._pool is not None
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO nanobot_memory.collections "
                    "(workspace_namespace, embedding_model, embedding_dimension) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (workspace_namespace) DO UPDATE SET updated_at = now() "
                    "WHERE nanobot_memory.collections.embedding_model = EXCLUDED.embedding_model "
                    "AND nanobot_memory.collections.embedding_dimension = EXCLUDED.embedding_dimension "
                    "RETURNING embedding_model, embedding_dimension",
                    (namespace, self._model_id, self._dimension),
                )
                row = await cur.fetchone()
                if row is None:
                    raise RuntimeError(
                        "semantic memory collection uses a different embedding model; reindex required"
                    )

    async def existing_hashes(
        self,
        namespace: str,
        keys: Sequence[tuple[str, str]],
    ) -> dict[tuple[str, str], str]:
        if not keys:
            return {}
        await self.ensure_collection(namespace)
        assert self._pool is not None
        wanted = set(keys)
        result: dict[tuple[str, str], str] = {}
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT source_type, source_key, content_hash "
                    "FROM nanobot_memory.items "
                    "WHERE workspace_namespace=%s AND embedding_model=%s",
                    (namespace, self._model_id),
                )
                for row in await cur.fetchall():
                    key = (str(row[0]), str(row[1]))
                    if key in wanted:
                        result[key] = str(row[2])
        return result

    async def upsert(
        self,
        namespace: str,
        records: Sequence[MemoryRecord],
        *,
        force: bool = False,
    ) -> None:
        if not records:
            return
        await self.ensure_collection(namespace)
        assert self._pool is not None
        statement = """
            INSERT INTO nanobot_memory.items (
                workspace_namespace, embedding_model, source_type, source_key,
                source_timestamp, session_key, kind, content, content_hash,
                importance, confidence, metadata, embedding
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector
            )
            ON CONFLICT (workspace_namespace, embedding_model, source_type, source_key)
            DO UPDATE SET
                source_timestamp=EXCLUDED.source_timestamp,
                session_key=EXCLUDED.session_key,
                kind=EXCLUDED.kind,
                content=EXCLUDED.content,
                content_hash=EXCLUDED.content_hash,
                importance=EXCLUDED.importance,
                confidence=EXCLUDED.confidence,
                metadata=EXCLUDED.metadata,
                embedding=EXCLUDED.embedding,
                status='active',
                updated_at=now()
        """
        if not force:
            statement += (
                " WHERE nanobot_memory.items.content_hash "
                "IS DISTINCT FROM EXCLUDED.content_hash"
            )
        params = [
            (
                namespace,
                self._model_id,
                record.source_type,
                record.source_key,
                record.source_timestamp,
                record.session_key,
                record.kind,
                record.content,
                record.content_hash,
                record.importance,
                record.confidence,
                json.dumps(record.metadata, ensure_ascii=False),
                "[" + ",".join(format(value, ".9g") for value in record.embedding) + "]",
            )
            for record in records
        ]
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(statement, params)

    async def hybrid_search(
        self,
        namespace: str,
        *,
        query: str,
        embedding: Sequence[float],
        session_key: str | None,
        scope: str,
        candidate_k: int,
        top_k: int,
        min_score: float,
        min_vector_similarity: float,
    ) -> list[SemanticHit]:
        await self.ensure_collection(namespace)
        assert self._pool is not None
        vector = "[" + ",".join(format(value, ".9g") for value in embedding) + "]"
        session_filter = ""
        if scope == "session":
            session_filter = (
                " AND (session_key = %s OR "
                "(session_key IS NULL AND source_type IN ('memory', 'user')))"
            )
        sql = f"""
            WITH vector_ranked AS (
                SELECT id, row_number() OVER (ORDER BY embedding <=> %s::vector) AS rank
                FROM nanobot_memory.items
                WHERE workspace_namespace=%s AND embedding_model=%s AND status='active'
                {session_filter}
                AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            ), lexical_ranked AS (
                SELECT id, row_number() OVER (
                    ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('simple', %s)) DESC
                ) AS rank
                FROM nanobot_memory.items
                WHERE workspace_namespace=%s AND embedding_model=%s AND status='active'
                {session_filter}
                AND search_vector @@ websearch_to_tsquery('simple', %s)
                ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('simple', %s)) DESC
                LIMIT %s
            ), fused AS (
                SELECT COALESCE(v.id, l.id) AS id,
                       COALESCE(1.0 / (60 + v.rank), 0) +
                       COALESCE(1.0 / (60 + l.rank), 0) AS score
                FROM vector_ranked v FULL OUTER JOIN lexical_ranked l USING (id)
            )
            SELECT i.source_type, i.source_key, i.content, i.source_timestamp,
                   i.session_key, i.kind,
                   f.score + (i.importance * 0.001) +
                       CASE WHEN i.kind='correction' THEN 0.002 ELSE 0 END AS adjusted_score,
                   i.importance, i.confidence, i.id
            FROM fused f JOIN nanobot_memory.items i ON i.id=f.id
            WHERE f.score >= %s
            ORDER BY adjusted_score DESC, i.updated_at DESC
            LIMIT %s
        """
        # SQL placeholders appear in vector CTE, lexical CTE, then final ranking.
        vector_scope = [namespace, self._model_id] + ([session_key] if scope == "session" else [])
        lexical_scope = [namespace, self._model_id] + ([session_key] if scope == "session" else [])
        params = [
            vector,
            *vector_scope,
            vector,
            min_vector_similarity,
            vector,
            candidate_k,
            query,
            *lexical_scope,
            query,
            query,
            candidate_k,
            min_score,
            top_k,
        ]
        hits: list[SemanticHit] = []
        ids: list[int] = []
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                for row in await cur.fetchall():
                    hits.append(SemanticHit(
                        source_type=str(row[0]),
                        source_key=str(row[1]),
                        content=str(row[2]),
                        source_timestamp=str(row[3]) if row[3] is not None else None,
                        session_key=str(row[4]) if row[4] is not None else None,
                        kind=str(row[5]),
                        score=float(row[6]),
                        importance=float(row[7]),
                        confidence=float(row[8]),
                    ))
                    ids.append(int(row[9]))
                if ids:
                    await cur.execute(
                        "UPDATE nanobot_memory.items SET last_accessed_at=now() WHERE id = ANY(%s)",
                        (ids,),
                    )
        return hits

    async def log_retrieval(
        self,
        namespace: str,
        session_key: str | None,
        query_hash: str,
        hit_count: int,
        latency_ms: int,
    ) -> None:
        if self._pool is None:
            return
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO nanobot_memory.retrieval_log "
                    "(workspace_namespace, session_key, query_hash, hit_count, latency_ms) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (namespace, session_key, query_hash, hit_count, latency_ms),
                )

    async def status(self, namespace: str) -> dict[str, Any]:
        await self.ensure_collection(namespace)
        assert self._pool is not None
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT count(*), max(updated_at), max(last_accessed_at) "
                    "FROM nanobot_memory.items WHERE workspace_namespace=%s AND embedding_model=%s",
                    (namespace, self._model_id),
                )
                row = await cur.fetchone()
        return {
            "items": int(row[0]) if row else 0,
            "last_updated": row[1].isoformat() if row and row[1] else None,
            "last_accessed": row[2].isoformat() if row and row[2] else None,
        }

    async def purge(self, namespace: str) -> int:
        await self.open()
        assert self._pool is not None
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        "DELETE FROM nanobot_memory.items WHERE workspace_namespace=%s",
                        (namespace,),
                    )
                    count = cur.rowcount or 0
                    await cur.execute(
                        "DELETE FROM nanobot_memory.tombstones WHERE workspace_namespace=%s",
                        (namespace,),
                    )
                    await cur.execute(
                        "DELETE FROM nanobot_memory.forgotten_content "
                        "WHERE workspace_namespace=%s",
                        (namespace,),
                    )
                    await cur.execute(
                        "DELETE FROM nanobot_memory.retrieval_log WHERE workspace_namespace=%s",
                        (namespace,),
                    )
                    await cur.execute(
                        "DELETE FROM nanobot_memory.collections WHERE workspace_namespace=%s",
                        (namespace,),
                    )
                    return count

    async def close(self) -> None:
        async with self._open_lock:
            pool, self._pool = self._pool, None
            if pool is not None:
                await pool.close()

    async def prune_stale(
        self,
        namespace: str,
        *,
        current_keys: set[tuple[str, str]],
        present_history_cursors: set[int],
    ) -> int:
        """Drop obsolete chunks without deleting legitimately compacted history."""
        await self.ensure_collection(namespace)
        assert self._pool is not None
        obsolete: list[int] = []
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, source_type, source_key FROM nanobot_memory.items "
                    "WHERE workspace_namespace=%s AND embedding_model=%s",
                    (namespace, self._model_id),
                )
                for row in await cur.fetchall():
                    item_id, source_type, source_key = int(row[0]), str(row[1]), str(row[2])
                    key = (source_type, source_key)
                    if key in current_keys:
                        continue
                    if source_type in {"memory", "user"}:
                        obsolete.append(item_id)
                    elif source_type == "history" and source_key.startswith("cursor:"):
                        with_cursor = source_key.split(":", 2)[1]
                        if with_cursor.isdigit() and int(with_cursor) in present_history_cursors:
                            obsolete.append(item_id)
                if obsolete:
                    await cur.execute(
                        "DELETE FROM nanobot_memory.items WHERE id = ANY(%s)",
                        (obsolete,),
                    )
        return len(obsolete)

    async def tombstoned_entries(
        self,
        namespace: str,
    ) -> tuple[set[tuple[str, str]], set[str]]:
        """Return legacy positional tombstones and stable forgotten content hashes."""
        await self.open()
        assert self._pool is not None
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT source_type, source_key, content_hash "
                    "FROM nanobot_memory.tombstones WHERE workspace_namespace=%s",
                    (namespace,),
                )
                rows = await cur.fetchall()
                await cur.execute(
                    "SELECT content_hash FROM nanobot_memory.forgotten_content "
                    "WHERE workspace_namespace=%s",
                    (namespace,),
                )
                forgotten_hashes = {str(row[0]) for row in await cur.fetchall()}
        return (
            {(str(row[0]), str(row[1])) for row in rows if row[2] is None},
            forgotten_hashes | {str(row[2]) for row in rows if row[2] is not None},
        )

    async def forget(
        self,
        namespace: str,
        source_type: str,
        source_key: str,
        *,
        reason: str = "user request",
    ) -> int:
        """Delete one derived record and prevent automatic re-ingestion."""
        await self.open()
        assert self._pool is not None
        async with self._pool.connection() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT content_hash FROM nanobot_memory.items "
                        "WHERE workspace_namespace=%s AND source_type=%s AND source_key=%s",
                        (namespace, source_type, source_key),
                    )
                    row = await cur.fetchone()
                    content_hash = str(row[0]) if row is not None else None
                    if content_hash is not None:
                        await cur.execute(
                            "INSERT INTO nanobot_memory.forgotten_content "
                            "(workspace_namespace, content_hash, source_type, source_key, reason) "
                            "VALUES (%s, %s, %s, %s, %s) "
                            "ON CONFLICT (workspace_namespace, content_hash) DO UPDATE SET "
                            "reason=EXCLUDED.reason",
                            (namespace, content_hash, source_type, source_key, reason),
                        )
                    await cur.execute(
                        "INSERT INTO nanobot_memory.tombstones "
                        "(workspace_namespace, source_type, source_key, content_hash, reason) "
                        "VALUES (%s, %s, %s, %s, %s) "
                        "ON CONFLICT (workspace_namespace, source_type, source_key) "
                        "DO UPDATE SET content_hash=COALESCE(EXCLUDED.content_hash, "
                        "nanobot_memory.tombstones.content_hash), "
                        "reason=EXCLUDED.reason, created_at=now()",
                        (namespace, source_type, source_key, content_hash, reason),
                    )
                    if content_hash is None:
                        await cur.execute(
                            "DELETE FROM nanobot_memory.items "
                            "WHERE workspace_namespace=%s AND "
                            "source_type=%s AND source_key=%s",
                            (namespace, source_type, source_key),
                        )
                    else:
                        await cur.execute(
                            "DELETE FROM nanobot_memory.items "
                            "WHERE workspace_namespace=%s AND "
                            "((source_type=%s AND source_key=%s) OR content_hash=%s)",
                            (namespace, source_type, source_key, content_hash),
                        )
                    return cur.rowcount or 0
