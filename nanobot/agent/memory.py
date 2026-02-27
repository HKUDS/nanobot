"""Memory system for persistent agent memory."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class VectorStore:
    """ChromaDB-based vector store for semantic memory search."""

    def __init__(self, memory_dir: Path):
        self.db_path = memory_dir / "vectordb"
        self._client = None
        self._collection = None
        self._available = None

    @property
    def available(self) -> bool:
        """Check if ChromaDB is available."""
        if self._available is None:
            try:
                import chromadb  # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
                logger.debug("ChromaDB not installed, vector search disabled")
        return self._available

    def _get_collection(self):
        """Lazy-load ChromaDB collection."""
        if self._collection is None and self.available:
            try:
                import chromadb
                self._client = chromadb.PersistentClient(path=str(self.db_path))
                self._collection = self._client.get_or_create_collection(
                    name="history",
                    metadata={"hnsw:space": "cosine"}
                )
                logger.debug("ChromaDB collection loaded: {} documents", self._collection.count())
            except Exception as e:
                logger.warning("Failed to initialize ChromaDB: {}", e)
                self._available = False
        return self._collection

    def add(self, text: str, metadata: dict | None = None) -> bool:
        """Add a document to the vector store."""
        collection = self._get_collection()
        if not collection:
            return False

        try:
            # Generate unique ID from content hash + timestamp
            doc_id = hashlib.md5(f"{text}{datetime.now().isoformat()}".encode()).hexdigest()[:16]
            meta = metadata or {}
            meta["timestamp"] = datetime.now().isoformat()

            collection.add(
                documents=[text],
                ids=[doc_id],
                metadatas=[meta]
            )
            logger.debug("Added document to vector store: {}", doc_id)
            return True
        except Exception as e:
            logger.warning("Failed to add to vector store: {}", e)
            return False

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search for similar documents.
        
        Returns list of dicts with 'text', 'score', and 'metadata' keys.
        """
        collection = self._get_collection()
        if not collection or collection.count() == 0:
            return []

        try:
            results = collection.query(
                query_texts=[query],
                n_results=min(top_k, collection.count())
            )

            docs = []
            if results and results.get("documents"):
                for i, doc in enumerate(results["documents"][0]):
                    docs.append({
                        "text": doc,
                        "score": 1 - results["distances"][0][i] if results.get("distances") else 0,
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {}
                    })
            return docs
        except Exception as e:
            logger.warning("Vector search failed: {}", e)
            return []

    def count(self) -> int:
        """Get number of documents in the store."""
        collection = self._get_collection()
        return collection.count() if collection else 0

    def reindex_history(self, history_file: Path) -> int:
        """Reindex HISTORY.md into the vector store.
        
        Returns number of documents indexed.
        """
        if not history_file.exists():
            return 0

        collection = self._get_collection()
        if not collection:
            return 0

        try:
            content = history_file.read_text(encoding="utf-8")
            # Split by double newline (paragraph separator)
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

            if not paragraphs:
                return 0

            # Clear existing and re-add
            # Get all existing IDs and delete them
            existing = collection.get()
            if existing and existing.get("ids"):
                collection.delete(ids=existing["ids"])

            # Add all paragraphs
            ids = [hashlib.md5(p.encode()).hexdigest()[:16] for p in paragraphs]
            metadatas = [{"source": "history"} for _ in paragraphs]

            collection.add(
                documents=paragraphs,
                ids=ids,
                metadatas=metadatas
            )

            logger.info("Reindexed {} paragraphs from HISTORY.md", len(paragraphs))
            return len(paragraphs)
        except Exception as e:
            logger.warning("Failed to reindex history: {}", e)
            return 0


class MemoryStore:
    """Three-layer memory: MEMORY.md (facts) + TACIT.md (patterns) + HISTORY.md (events) + VectorDB (semantic search)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.tacit_file = self.memory_dir / "TACIT.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.vector_store = VectorStore(self.memory_dir)

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def read_tacit(self) -> str:
        if self.tacit_file.exists():
            return self.tacit_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")
        # Also add to vector store for semantic search
        self.vector_store.add(entry, {"source": "consolidation"})

    def search_history(self, query: str, top_k: int = 5) -> list[dict]:
        """Semantic search over history using vector store.
        
        Falls back to empty list if vector store unavailable.
        """
        return self.vector_store.search(query, top_k)

    def reindex_vector_store(self) -> int:
        """Rebuild vector store from HISTORY.md."""
        return self.vector_store.reindex_history(self.history_file)

    def get_memory_context(self) -> str:
        """Get combined memory context (long-term + tacit)."""
        parts = []
        
        long_term = self.read_long_term()
        if long_term:
            parts.append(long_term)
        
        tacit = self.read_tacit()
        if tacit:
            parts.append(f"\n\n## Tacit Knowledge\n{tacit}")
        
        return parts[0] + (parts[1] if len(parts) > 1 else "") if parts else ""

    def get_relevant_history(self, query: str, top_k: int = 3) -> str:
        """Get relevant history entries for a query (semantic search)."""
        results = self.search_history(query, top_k)
        if not results:
            return ""
        
        entries = [f"- {r['text'][:200]}..." if len(r['text']) > 200 else f"- {r['text']}" 
                   for r in results]
        return "## Relevant Past Events\n" + "\n".join(entries)

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return True
            logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation."},
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            # Some providers return arguments as a JSON string instead of dict
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
