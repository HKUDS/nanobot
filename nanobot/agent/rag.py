"""RAG (Retrieval-Augmented Generation) layer for semantic memory search.

Augments the existing two-layer memory system (MEMORY.md + HISTORY.md) with
ChromaDB-backed semantic search across conversations, documents, and facts.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 500        # target chars per document chunk
_CHUNK_OVERLAP = 80      # overlap between consecutive chunks
_MSG_WINDOW = 4          # messages per conversation window
_MSG_STEP = 2            # step between windows (creates overlap)
_SUPPORTED_SUFFIXES = {
    ".md", ".txt", ".py", ".json",
    ".pdf", ".docx", ".doc",
    ".csv", ".html", ".htm", ".xml",
    ".yaml", ".yml", ".rst", ".log",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().isoformat()


def _chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph boundaries."""
    if not text or not text.strip():
        return []

    # First try to split on double-newlines (paragraphs).
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            # Para itself may be larger than chunk_size — hard split it.
            if len(para) > chunk_size:
                for i in range(0, len(para), chunk_size - overlap):
                    piece = para[i : i + chunk_size]
                    if piece.strip():
                        chunks.append(piece.strip())
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    # If we only have one big block (no paragraph breaks) fall back to hard split.
    if not chunks:
        for i in range(0, len(text), chunk_size - overlap):
            piece = text[i : i + chunk_size].strip()
            if piece:
                chunks.append(piece)

    return chunks


def _window_messages(messages: list[dict], window: int = _MSG_WINDOW, step: int = _MSG_STEP) -> list[str]:
    """Produce overlapping windows of messages as text blocks."""
    blocks: list[str] = []
    for i in range(0, max(1, len(messages) - window + 1), step):
        segment = messages[i : i + window]
        lines = []
        for m in segment:
            if not m.get("content"):
                continue
            role = m.get("role", "?").upper()
            ts = m.get("timestamp", "")[:16]
            prefix = f"[{ts}] {role}: " if ts else f"{role}: "
            content = m["content"]
            if not isinstance(content, str):
                content = str(content)
            lines.append(prefix + content[:800])
        text = "\n".join(lines).strip()
        if text:
            blocks.append(text)
    return blocks


def _extract_text(file_path: Path) -> str:
    """Extract text content from a file, handling binary formats (PDF, DOCX)."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not installed, skipping PDF: {}", file_path)
            return ""
        pages: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
        return "\n\n".join(pages)

    if suffix in (".docx", ".doc"):
        try:
            import docx as python_docx
        except ImportError:
            logger.warning("python-docx not installed, skipping DOCX: {}", file_path)
            return ""
        doc = python_docx.Document(str(file_path))
        return "\n\n".join(
            para.text for para in doc.paragraphs if para.text.strip()
        )

    # All other supported types are text-based.
    return file_path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# RAGStore
# ---------------------------------------------------------------------------

class RAGStore:
    """ChromaDB-backed semantic store with three collections.

    Collections
    -----------
    conversations  — windowed chunks from live/consolidated sessions
    documents      — ingested files (markdown, text, code, JSON)
    knowledge      — individual facts extracted from consolidation
    """

    COLLECTIONS = ("conversations", "documents", "knowledge")

    def __init__(self, workspace: Path) -> None:
        self.rag_dir = ensure_dir(workspace / "rag")
        self._client = None
        self._cols: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Lazy initialization
    # ------------------------------------------------------------------

    def _get_client(self):
        """Return (and lazily create) the ChromaDB persistent client."""
        if self._client is None:
            try:
                import chromadb
            except ImportError as exc:
                raise RuntimeError(
                    "chromadb is not installed. Run: pip install chromadb"
                ) from exc
            self._client = chromadb.PersistentClient(path=str(self.rag_dir))
            logger.debug("ChromaDB client initialised at {}", self.rag_dir)
        return self._client

    def _col(self, name: str):
        """Return (and cache) a ChromaDB collection, creating it if absent."""
        if name not in self._cols:
            client = self._get_client()
            # get_or_create uses the default embedding function
            # (all-MiniLM-L6-v2 via sentence-transformers, auto-downloaded).
            self._cols[name] = client.get_or_create_collection(name)
            logger.debug("Collection '{}' ready", name)
        return self._cols[name]

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def add_conversation(
        self,
        session_id: str,
        messages: list[dict],
        timestamp: str | None = None,
    ) -> None:
        """Chunk a list of message dicts and embed them in the conversations collection."""
        if not messages:
            return
        ts = timestamp or _now_iso()
        blocks = _window_messages(messages)
        if not blocks:
            return

        col = self._col("conversations")
        ids, docs, metas = [], [], []
        for idx, block in enumerate(blocks):
            uid = f"{session_id}__{ts}__{idx}"
            ids.append(uid)
            docs.append(block)
            metas.append({"session_id": session_id, "timestamp": ts, "chunk_index": idx})

        try:
            col.upsert(ids=ids, documents=docs, metadatas=metas)
            logger.debug("RAG: upserted {} conversation chunk(s) for session {}", len(ids), session_id)
        except Exception:
            logger.exception("RAG: failed to upsert conversation chunks for session {}", session_id)

    def add_document(
        self,
        path: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        """Chunk a document and embed it in the documents collection."""
        if not content or not content.strip():
            logger.warning("RAG: skipping empty document {}", path)
            return

        chunks = _chunk_text(content)
        if not chunks:
            return

        col = self._col("documents")
        safe_path = path.replace("/", "_").replace("\\", "_").replace(":", "_")
        ts = _now_iso()
        base_meta = {"path": path, "timestamp": ts, **(metadata or {})}

        ids, docs, metas = [], [], []
        for idx, chunk in enumerate(chunks):
            uid = f"doc__{safe_path}__{idx}"
            ids.append(uid)
            docs.append(chunk)
            metas.append({**base_meta, "chunk_index": idx, "total_chunks": len(chunks)})

        try:
            col.upsert(ids=ids, documents=docs, metadatas=metas)
            logger.debug("RAG: upserted {} chunk(s) for document {}", len(ids), path)
        except Exception:
            logger.exception("RAG: failed to upsert document {}", path)

    def add_knowledge(
        self,
        fact: str,
        source: str = "consolidation",
        timestamp: str | None = None,
    ) -> None:
        """Store a single fact/entity in the knowledge collection."""
        fact = fact.strip()
        if not fact:
            return

        ts = timestamp or _now_iso()
        col = self._col("knowledge")
        # Stable ID based on content hash so duplicate facts are deduplicated.
        uid = "fact__" + hashlib.sha1(fact.encode()).hexdigest()[:16]

        try:
            col.upsert(
                ids=[uid],
                documents=[fact],
                metadatas=[{"source": source, "timestamp": ts}],
            )
            logger.debug("RAG: upserted knowledge fact ({}…)", fact[:60])
        except Exception:
            logger.exception("RAG: failed to upsert knowledge fact")

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n_results: int = 5,
        collection: str | None = None,
    ) -> list[dict]:
        """Semantic search across one or all collections.

        Returns a flat list of dicts with keys:
            content, metadata, distance, collection
        sorted by distance (ascending = most similar first).
        """
        if not query or not query.strip():
            return []

        target_cols = [collection] if collection else list(self.COLLECTIONS)
        results: list[dict] = []

        for col_name in target_cols:
            try:
                col = self._col(col_name)
                count = col.count()
                if count == 0:
                    continue
                k = min(n_results, count)
                raw = col.query(query_texts=[query], n_results=k)
                docs = raw.get("documents", [[]])[0]
                metas = raw.get("metadatas", [[]])[0]
                dists = raw.get("distances", [[]])[0]
                for doc, meta, dist in zip(docs, metas, dists):
                    results.append(
                        {
                            "content": doc,
                            "metadata": meta,
                            "distance": dist,
                            "collection": col_name,
                        }
                    )
            except Exception:
                logger.exception("RAG: search failed in collection '{}'", col_name)

        results.sort(key=lambda r: r["distance"])
        return results[:n_results]

    # ------------------------------------------------------------------
    # Migration / bulk ingestion
    # ------------------------------------------------------------------

    def ingest_history(self, history_file: Path) -> int:
        """Parse HISTORY.md and embed each entry in the conversations collection.

        Returns the number of entries ingested.
        """
        if not history_file.exists():
            logger.info("RAG: history file not found, skipping ingest: {}", history_file)
            return 0

        text = history_file.read_text(encoding="utf-8")
        # Each entry is separated by blank lines; entries start with a timestamp.
        entries = [e.strip() for e in re.split(r"\n\n+", text) if e.strip()]
        if not entries:
            return 0

        col = self._col("conversations")
        ids, docs, metas = [], [], []

        for idx, entry in enumerate(entries):
            # Try to extract the timestamp from the entry header [YYYY-MM-DD HH:MM]
            m = re.match(r"\[(\d{4}-\d{2}-\d{2}[^\]]*)\]", entry)
            ts = m.group(1) if m else _now_iso()
            uid = f"history__{idx}__{ts.replace(' ', 'T')[:19]}"
            ids.append(uid)
            docs.append(entry)
            metas.append({"source": "HISTORY.md", "timestamp": ts, "entry_index": idx})

        try:
            col.upsert(ids=ids, documents=docs, metadatas=metas)
            logger.info("RAG: ingested {} HISTORY.md entries", len(ids))
        except Exception:
            logger.exception("RAG: failed to ingest HISTORY.md")
            return 0

        return len(entries)

    def ingest_directory(self, dir_path: Path, glob: str = "**/*.md") -> int:
        """Bulk-ingest all matching files from a directory.

        Returns the number of files successfully ingested.
        """
        if not dir_path.is_dir():
            logger.warning("RAG: ingest_directory path is not a directory: {}", dir_path)
            return 0

        count = 0
        for file_path in sorted(dir_path.glob(glob)):
            if file_path.suffix not in _SUPPORTED_SUFFIXES:
                continue
            try:
                content = _extract_text(file_path)
                if not content or not content.strip():
                    logger.debug("RAG: skipping empty file {}", file_path)
                    continue
                self.add_document(
                    path=str(file_path),
                    content=content,
                    metadata={"source": "directory_ingest", "filename": file_path.name},
                )
                count += 1
            except Exception:
                logger.exception("RAG: failed to ingest file {}", file_path)

        logger.info("RAG: ingest_directory ingested {} file(s) from {}", count, dir_path)
        return count

    # ------------------------------------------------------------------
    # Helpers for consolidation integration
    # ------------------------------------------------------------------

    def extract_and_store_facts(
        self,
        history_entry: str,
        memory_update: str,
        timestamp: str | None = None,
    ) -> None:
        """Extract bullet-point facts from a memory update and store them individually.

        Intended to be called right after consolidation so the knowledge
        collection stays current without requiring a separate LLM call.
        """
        ts = timestamp or _now_iso()
        # Collect lines that look like facts: bullet/numbered lists, or sentences.
        candidates: list[str] = []

        for line in memory_update.splitlines():
            stripped = line.strip()
            # Skip headings, empty lines, and very short lines.
            if not stripped or stripped.startswith("#") or len(stripped) < 10:
                continue
            # Remove leading bullet/numbering markers.
            cleaned = re.sub(r"^[-*+\d.)\s]+", "", stripped).strip()
            if len(cleaned) >= 10:
                candidates.append(cleaned)

        # Also treat the full history entry as a single knowledge chunk.
        if history_entry and history_entry.strip():
            self.add_knowledge(history_entry.strip(), source="history_entry", timestamp=ts)

        for fact in candidates:
            self.add_knowledge(fact, source="memory_update", timestamp=ts)

        logger.debug("RAG: stored {} facts from consolidation", len(candidates))
