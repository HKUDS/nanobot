"""Structured fact store with dual-mode retrieval (BM25S or sqlite-vec KNN)."""

from __future__ import annotations

import sqlite3
import struct
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.agent.embedding import EmbeddingClient
    from nanobot.config.schema import MemoryConfig

_SQLITE_VEC_AVAILABLE = False
try:
    import sqlite_vec  # noqa: F401
    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    pass

_BM25S_AVAILABLE = False
try:
    import bm25s
    _BM25S_AVAILABLE = True
except ImportError:
    pass


def _deserialize_float32(blob: bytes) -> list[float]:
    """Unpack float32 blob to list of floats."""
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


class FactStore:
    """
    SQLite-backed fact store with optional vector (sqlite-vec) or BM25S retrieval.
    When embedding_client is set and sqlite-vec is available, uses KNN.
    Otherwise uses BM25S for keyword retrieval (or flat list if bm25s missing).
    """

    def __init__(
        self,
        workspace: Path,
        memory_config: MemoryConfig | None = None,
        embedding_client: EmbeddingClient | None = None,
    ):
        self.workspace = Path(workspace)
        self.memory_dir = ensure_dir(self.workspace / "memory")
        self.db_path = self.memory_dir / "memory.db"
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.config = memory_config
        self.embedding_client = embedding_client
        self._conn: sqlite3.Connection | None = None
        self._dimensions = 0
        if memory_config and embedding_client:
            self._dimensions = getattr(
                memory_config.embedding,
                "dimensions",
                1024,
            )
        self._init_db()
        self._seed_from_memory_md()
        if self.embedding_client and _SQLITE_VEC_AVAILABLE and self._dimensions > 0:
            mode = "KNN (vector)"
        elif _BM25S_AVAILABLE:
            mode = "BM25S"
        else:
            mode = "recent"
        logger.info(
            "FactStore: initialized at {} (retrieval={}, embedding_dim={})",
            self.db_path,
            mode,
            self._dimensions if self.embedding_client else 0,
        )

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                embedding BLOB,
                tokens INTEGER,
                created_at TEXT,
                updated_at TEXT,
                access_count INTEGER DEFAULT 0,
                source_session TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                embedding BLOB,
                created_at TEXT
            )
        """)
        conn.commit()

    def _seed_from_memory_md(self) -> None:
        """One-time import: if DB has 0 facts but MEMORY.md exists, parse and seed it."""
        conn = self._get_conn()
        count = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        if count > 0:
            return
        if not self.memory_file.exists():
            return
        try:
            from nanobot.agent.budget import count_tokens
            text = self.memory_file.read_text(encoding="utf-8")
            category = "general"
            now = datetime.utcnow().isoformat() + "Z"
            added = 0
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("## "):
                    category = stripped[3:].strip()
                    continue
                if stripped.startswith("- "):
                    content = stripped[2:].strip()
                    if not content or content.startswith("("):
                        continue
                    tokens = count_tokens(content)
                    conn.execute(
                        "INSERT INTO facts (content, category, tokens, created_at, updated_at, access_count, source_session) VALUES (?, ?, ?, ?, ?, 0, ?)",
                        (content, category, tokens, now, now, "seed:MEMORY.md"),
                    )
                    added += 1
            if added:
                conn.commit()
                logger.info("FactStore: seeded {} facts from existing MEMORY.md", added)
        except Exception as e:
            logger.warning("FactStore: failed to seed from MEMORY.md: {}", e)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _get_all_facts(self) -> list[dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT id, content, category, access_count FROM facts ORDER BY id"
        )
        return [dict(row) for row in cur.fetchall()]

    def get_memory_context(
        self,
        query: str,
        token_budget: int = 800,
        query_embedding: list[float] | None = None,
    ) -> str:
        """
        Retrieve relevant facts for the query, within token budget.
        When query_embedding is provided and vec is available, uses KNN; else BM25S or recent.
        """
        facts = self._retrieve_facts(query, query_embedding=query_embedding)
        from nanobot.agent.budget import count_tokens

        parts = []
        used = 0
        for f in facts:
            content = f.get("content", "")
            t = count_tokens(content)
            if used + t > token_budget:
                break
            parts.append(content)
            used += t
            self._increment_access(f.get("id"))

        if not parts:
            logger.debug("FactStore: get_memory_context query='{}' -> 0 facts", query[:50] if query else "")
            return ""
        logger.debug(
            "FactStore: get_memory_context query='{}' -> {} facts, ~{} tokens",
            query[:50] if query else "",
            len(parts),
            used,
        )
        return "## Long-term Memory\n\n" + "\n\n".join(parts)

    def _retrieve_facts(
        self,
        query: str,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        top_k = 10
        if self.config:
            top_k = getattr(self.config, "retrieval_top_k", 10)

        if (
            query_embedding is not None
            and _SQLITE_VEC_AVAILABLE
            and self._dimensions > 0
        ):
            logger.debug("FactStore: _retrieve_facts using KNN, top_k={}", top_k)
            return self._knn_search(query_embedding, top_k)
        if _BM25S_AVAILABLE:
            logger.debug("FactStore: _retrieve_facts using BM25S, top_k={}", top_k)
            return self._bm25_search(query, top_k)
        logger.debug("FactStore: _retrieve_facts using recent, top_k={}", top_k)
        return self._recent_facts(top_k)

    def _knn_search(self, query_vec: list[float], top_k: int) -> list[dict[str, Any]]:
        """Vector KNN search using cosine similarity (query_vec from async embed)."""
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT id, content, category, embedding, access_count FROM facts WHERE embedding IS NOT NULL"
        )
        rows = cur.fetchall()
        if not rows:
            return self._recent_facts(top_k)
        import math
        scores = []
        for row in rows:
            other_blob = row["embedding"]
            if not other_blob:
                continue
            other = _deserialize_float32(other_blob)
            if len(other) != len(query_vec):
                continue
            dot = sum(a * b for a, b in zip(query_vec, other))
            na = math.sqrt(sum(a * a for a in query_vec))
            nb = math.sqrt(sum(b * b for b in other))
            sim = (dot / (na * nb)) if (na and nb) else 0
            boost = 1.0 + 0.1 * min(row["access_count"] or 0, 10)
            scores.append((sim * boost, dict(row)))
        scores.sort(key=lambda x: -x[0])
        return [s[1] for s in scores[:top_k]]

    def _bm25_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        """BM25 keyword search."""
        facts = self._get_all_facts()
        if not facts:
            return []
        corpus = [f["content"] for f in facts]
        tokenized = bm25s.tokenize(corpus)
        retriever = bm25s.BM25()
        retriever.index(tokenized)
        q_tok = bm25s.tokenize([query])
        doc_ids, scores = retriever.retrieve(q_tok, k=min(top_k, len(facts)))
        out = []
        for idx in doc_ids[0]:
            if 0 <= idx < len(facts):
                out.append(facts[idx])
        return out

    def _recent_facts(self, top_k: int) -> list[dict[str, Any]]:
        """Return most recent facts when no retrieval backend."""
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT id, content, category, access_count FROM facts ORDER BY updated_at DESC, id DESC LIMIT ?",
            (top_k,),
        )
        return [dict(row) for row in cur.fetchall()]

    def _increment_access(self, fact_id: int | None) -> None:
        if fact_id is None:
            return
        try:
            self._get_conn().execute(
                "UPDATE facts SET access_count = access_count + 1 WHERE id = ?",
                (fact_id,),
            )
            self._get_conn().commit()
        except Exception:
            pass

    async def add_facts(
        self,
        facts: list[dict[str, Any]],
        source_session: str = "",
    ) -> int:
        """
        Insert facts with optional embedding and dedup.
        Each fact: {content, category}. Returns number added.
        """
        from nanobot.agent.budget import count_tokens
        added = 0
        for f in facts:
            content = (f.get("content") or "").strip()
            if not content:
                continue
            category = f.get("category", "general")
            tokens = count_tokens(content)
            embedding_blob = None
            if self.embedding_client and _SQLITE_VEC_AVAILABLE and self._dimensions > 0:
                try:
                    vec = await self.embedding_client.embed(content, input_type="passage")
                    import sqlite_vec
                    embedding_blob = sqlite_vec.serialize_float32(vec)
                except Exception as e:
                    logger.warning("FactStore: embedding failed for fact, storing without vector: {}", e)
            now = datetime.utcnow().isoformat() + "Z"
            self._get_conn().execute(
                """INSERT INTO facts (content, category, embedding, tokens, created_at, updated_at, access_count, source_session)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
                (content, category, embedding_blob, tokens, now, now, source_session),
            )
            added += 1
        if added:
            self._get_conn().commit()
            self._export_memory_md()
            logger.info(
                "FactStore: add_facts added {} fact(s), session={}",
                added,
                source_session or "(none)",
            )
        return added

    def _export_memory_md(self) -> None:
        """Write MEMORY.md from current facts grouped by category."""
        facts = self._get_all_facts()
        by_cat: dict[str, list[str]] = {}
        for f in facts:
            cat = f.get("category", "general")
            by_cat.setdefault(cat, []).append(f.get("content", ""))
        lines = ["# Long-term Memory", ""]
        for cat in sorted(by_cat.keys()):
            lines.append(f"## {cat}")
            lines.append("")
            for c in by_cat[cat]:
                lines.append(f"- {c}")
            lines.append("")
        self.memory_file.write_text("\n".join(lines), encoding="utf-8")
        logger.debug("FactStore: exported MEMORY.md ({} categories, {} facts)", len(by_cat), len(facts))

    def get_relevant_history(
        self,
        query: str,
        top_k: int = 3,
        token_budget: int = 200,
    ) -> str:
        """Retrieve relevant history entries for the query within token budget."""
        try:
            conn = self._get_conn()
            cur = conn.execute(
                "SELECT id, content FROM history_entries ORDER BY id DESC LIMIT 500"
            )
            rows = cur.fetchall()
        except Exception:
            return ""
        if not rows:
            return ""
        entries = [dict(r) for r in rows]
        if _BM25S_AVAILABLE:
            corpus = [e["content"] for e in entries]
            tokenized = bm25s.tokenize(corpus)
            retriever = bm25s.BM25()
            retriever.index(tokenized)
            q_tok = bm25s.tokenize([query])
            doc_ids, _ = retriever.retrieve(q_tok, k=min(top_k, len(entries)))
            selected = []
            for idx in doc_ids[0]:
                if 0 <= idx < len(entries):
                    selected.append(entries[idx]["content"])
        else:
            selected = [e["content"] for e in entries[:top_k]]
        from nanobot.agent.budget import count_tokens
        parts = []
        used = 0
        for s in selected:
            t = count_tokens(s)
            if used + t > token_budget:
                break
            parts.append(s)
            used += t
        if not parts:
            return ""
        logger.debug(
            "FactStore: get_relevant_history query='{}' -> {} entries, ~{} tokens",
            query[:50] if query else "",
            len(parts),
            used,
        )
        return "## Relevant history\n\n" + "\n\n".join(parts)

    def append_history(self, entry: str) -> None:
        """Append to HISTORY.md and optionally to history_entries table."""
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")
        now = datetime.utcnow().isoformat() + "Z"
        try:
            self._get_conn().execute(
                "INSERT INTO history_entries (content, created_at) VALUES (?, ?)",
                (entry.strip(), now),
            )
            self._get_conn().commit()
        except Exception as e:
            logger.warning("FactStore: history_entries insert failed: {}", e)


def fact_store_available() -> bool:
    """True if at least one of sqlite-vec or bm25s is available for the store."""
    return _SQLITE_VEC_AVAILABLE or _BM25S_AVAILABLE
