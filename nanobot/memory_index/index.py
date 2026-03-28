"""MemoryIndex — lifecycle and public search interface."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import MemoryIndexConfig
    from nanobot.memory_index.search import SearchResult


class MemoryIndex:
    """Manages the SQLite memory index database."""

    def __init__(self, workspace: Path, config: MemoryIndexConfig) -> None:
        self.workspace = workspace
        self.config = config
        self.memory_dir = workspace / "memory"
        self.db_path = self.memory_dir / ".index.db"
        self._vec_available = False
        self._provider = None
        self._memory_dir_setup()
        self._check_vec_available()
        self._setup_db()
        self._setup_provider()

    def _memory_dir_setup(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _check_vec_available(self) -> None:
        """Check once at init whether sqlite-vec can be loaded."""
        try:
            import sqlite_vec as sv

            conn = sqlite3.connect(":memory:")
            conn.enable_load_extension(True)
            sv.load(conn)
            conn.close()
            self._vec_available = True
        except Exception as e:
            logger.warning("sqlite-vec unavailable, BM25-only search active: {}", e)

    def _open_conn(self) -> sqlite3.Connection:
        """Open a connection with sqlite-vec loaded if available."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if self._vec_available:
            import sqlite_vec

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        return conn

    def _setup_db(self) -> None:
        schema_sql = (Path(__file__).parent / "schema.sql").read_text()
        dim = self.config.embedding.dim

        if self.db_path.exists() and self._has_model_mismatch():
            logger.info("Embedding model changed, rebuilding memory index")
            self.db_path.unlink()

        conn = self._open_conn()
        try:
            conn.executescript(schema_sql)
            # executescript issues an implicit COMMIT; subsequent inserts start a new transaction
            if self._vec_available:
                conn.execute(
                    f"CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec "
                    f"USING vec0(embedding FLOAT[{dim}])"
                )
            row = conn.execute("SELECT 1 FROM index_meta WHERE key='embedding_model'").fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO index_meta(key, value) VALUES (?, ?)",
                    ["embedding_model", self.config.embedding.model],
                )
                conn.execute(
                    "INSERT INTO index_meta(key, value) VALUES (?, ?)",
                    ["embedding_dim", str(dim)],
                )
            conn.commit()
        finally:
            conn.close()

    def _has_model_mismatch(self) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT value FROM index_meta WHERE key='embedding_model'"
                ).fetchone()
                if not row:
                    return False
                if row[0] != self.config.embedding.model:
                    return True
                row2 = conn.execute(
                    "SELECT value FROM index_meta WHERE key='embedding_dim'"
                ).fetchone()
                if row2 and int(row2[0]) != self.config.embedding.dim:
                    return True
                return False
            finally:
                conn.close()
        except Exception:
            return False

    def _setup_provider(self) -> None:
        if self.config.embedding.provider == "ollama":
            from nanobot.memory_index.embeddings import OllamaEmbeddingProvider

            self._provider = OllamaEmbeddingProvider(
                base_url=self.config.embedding.base_url,
                model=self.config.embedding.model,
                batch_size=self.config.embedding.batch_size,
            )

    async def startup_index(self) -> None:
        """Re-index memory files at startup (skips unchanged files)."""
        memory_file = self.memory_dir / "MEMORY.md"
        history_file = self.memory_dir / "HISTORY.md"
        for path in [memory_file, history_file]:
            if path.exists():
                try:
                    await self._index_file(path)
                except Exception:
                    logger.exception("Failed to index {}", path.name)

    async def _index_file(self, path: Path) -> None:
        """Index a single file if its content has changed."""
        from nanobot.memory_index.indexer import (
            chunk_history_file,
            chunk_memory_file,
            file_hash,
            write_chunks,
        )

        current_hash = await asyncio.to_thread(file_hash, path)
        stat = path.stat()

        conn = self._open_conn()
        try:
            row = conn.execute("SELECT hash FROM files WHERE path = ?", [str(path)]).fetchone()
        finally:
            conn.close()

        if row and row["hash"] == current_hash:
            return  # unchanged

        if path.name == "MEMORY.md":
            chunks = await asyncio.to_thread(chunk_memory_file, path)
        else:
            chunks = await asyncio.to_thread(chunk_history_file, path)

        embeddings = None
        if self._vec_available and self._provider and chunks:
            from nanobot.memory_index.embeddings import EmbeddingUnavailableError

            try:
                embeddings = await self._provider.embed_batch([c.text for c in chunks])
            except EmbeddingUnavailableError:
                logger.warning(
                    "Ollama unavailable while indexing {}, storing without embeddings",
                    path.name,
                )

        await asyncio.to_thread(
            write_chunks,
            self.db_path,
            path,
            stat.st_mtime,
            stat.st_size,
            current_hash,
            chunks,
            embeddings,
            self._vec_available,
        )
        logger.info("Indexed {} ({} chunks)", path.name, len(chunks))

    async def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        """Hybrid BM25+vector search with temporal decay and MMR."""
        from nanobot.memory_index.embeddings import EmbeddingUnavailableError
        from nanobot.memory_index.search import sync_search

        k = top_k or self.config.query.top_k
        query_vec = None

        if self._vec_available and self._provider:
            try:
                vecs = await self._provider.embed_batch([query])
                query_vec = vecs[0]
            except EmbeddingUnavailableError:
                logger.debug("Ollama unavailable during search, using BM25-only")

        return await asyncio.to_thread(
            sync_search,
            self.db_path,
            query,
            query_vec,
            k,
            self._vec_available,
            self.config.query.mmr_lambda,
            self.config.query.temporal_decay_half_life_days,
        )
