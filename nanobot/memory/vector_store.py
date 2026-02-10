"""
Vector-based memory store using Mem0 + ChromaDB.

Mem0 handles:
  - Memory extraction from conversations (via LLM)
  - Deduplication and conflict resolution
  - Embedding and vector search

ChromaDB is used as the underlying persistent vector store.
"""

from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.memory.base import BaseMemoryStore
from nanobot.memory.types import MemoryItem, MemorySearchResult
from nanobot.utils.helpers import ensure_dir


class VectorMemoryStore(BaseMemoryStore):
    """
    Long-term memory backed by Mem0 (with ChromaDB vector store).

    Configuration is provided via MemoryConfig from nanobot's config schema.
    Falls back gracefully if Mem0/ChromaDB are unavailable.
    """

    def __init__(self, workspace: Path, config=None):
        super().__init__(workspace)
        self._config = config
        try:
            self._mem0 = self._init_mem0(workspace, config)
            self._available = True
            logger.info("VectorMemoryStore initialized (Mem0 + ChromaDB)")
        except Exception as e:
            self._mem0 = None
            self._available = False
            logger.error(
                f"VectorMemoryStore init failed: {e}. "
                "Check your API keys (OPENAI_API_KEY, etc). "
                "Memory operations will return empty results."
            )

    def _init_mem0(self, workspace: Path, config):
        """Initialize Mem0 with ChromaDB backend."""
        from mem0 import Memory

        chroma_path = str(ensure_dir(workspace / "memory" / ".chromadb"))
        collection_name = "nanobot_memories"

        # Build Mem0 config dict
        mem0_config: dict[str, Any] = {
            "vector_store": {
                "provider": "chroma",
                "config": {
                    "collection_name": collection_name,
                    "path": chroma_path,
                },
            },
        }

        # Configure LLM — reuse nanobot's existing provider if possible
        if config and getattr(config, "llm_provider", None):
            mem0_config["llm"] = {
                "provider": config.llm_provider,
                "config": self._build_llm_config(config),
            }
        else:
            # Default: try litellm which works with whatever provider nanobot uses
            mem0_config["llm"] = {
                "provider": "litellm",
                "config": {
                    "model": getattr(config, "llm_model", "openai/gpt-4o-mini")
                    if config
                    else "openai/gpt-4o-mini",
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            }

        # Configure embedder
        if config and getattr(config, "embedder_provider", None):
            mem0_config["embedder"] = {
                "provider": config.embedder_provider,
                "config": self._build_embedder_config(config),
            }
        else:
            # Default: openai embeddings (most reliable)
            mem0_config["embedder"] = {
                "provider": "openai",
                "config": {
                    "model": getattr(config, "embedding_model", "text-embedding-3-small")
                    if config
                    else "text-embedding-3-small",
                },
            }

        # Custom prompt for memory extraction tuned to nanobot's use case
        mem0_config["custom_fact_extraction_prompt"] = self._get_extraction_prompt()

        return Memory.from_config(mem0_config)

    # ── BaseMemoryStore interface ──────────────────────────────────────

    def search(
        self, query: str, user_id: str | None = None, limit: int = 8
    ) -> MemorySearchResult:
        """
        Semantic search for relevant memories.

        Args:
            query: Search query (typically user message + task context).
            user_id: Session key for user-scoped memories.
            limit: Max results to return.

        Returns:
            MemorySearchResult with scored memories.
        """
        if not self._available:
            return MemorySearchResult(memories=[], query=query, total_found=0)

        try:
            kwargs: dict[str, Any] = {"query": query, "limit": limit}
            if user_id:
                kwargs["user_id"] = user_id

            results = self._mem0.search(**kwargs)

            items = []
            # Mem0 search returns a dict with 'results' key
            raw_results = results.get("results", results) if isinstance(results, dict) else results
            for r in raw_results:
                item = self._mem0_result_to_item(r)
                items.append(item)

            return MemorySearchResult(
                memories=items,
                query=query,
                total_found=len(items),
            )

        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return MemorySearchResult(memories=[], query=query, total_found=0)

    def add(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> list[MemoryItem]:
        """
        Extract and store memories from conversation messages.

        Mem0 internally uses an LLM to identify facts, preferences, and
        important information worth remembering.

        Args:
            messages: Conversation turn [{"role": "user", "content": "..."}, ...].
            user_id: Session key for user-scoped storage.
            metadata: Extra metadata to attach to stored memories.

        Returns:
            List of newly created/updated MemoryItems.
        """
        if not self._available:
            return []

        try:
            kwargs: dict[str, Any] = {"messages": messages}
            if user_id:
                kwargs["user_id"] = user_id
            if metadata:
                kwargs["metadata"] = metadata

            result = self._mem0.add(**kwargs)

            items = []
            # Mem0 add returns a dict with 'results' key
            raw_results = result.get("results", result) if isinstance(result, dict) else result
            if isinstance(raw_results, list):
                for r in raw_results:
                    item = self._mem0_result_to_item(r)
                    items.append(item)

            if items:
                logger.debug(f"Stored {len(items)} memories for user={user_id}")
            return items

        except Exception as e:
            logger.error(f"Memory add failed: {e}")
            return []

    def get_all(self, user_id: str | None = None, limit: int = 100) -> list[MemoryItem]:
        """Get all stored memories."""
        if not self._available:
            return []

        try:
            kwargs: dict[str, Any] = {"limit": limit}
            if user_id:
                kwargs["user_id"] = user_id

            results = self._mem0.get_all(**kwargs)

            items = []
            raw_results = results.get("results", results) if isinstance(results, dict) else results
            for r in raw_results:
                item = self._mem0_result_to_item(r)
                items.append(item)
            return items

        except Exception as e:
            logger.error(f"Memory get_all failed: {e}")
            return []

    def delete(self, memory_id: str) -> bool:
        """Delete a specific memory by ID."""
        if not self._available:
            return False

        try:
            self._mem0.delete(memory_id)
            return True
        except Exception as e:
            logger.error(f"Memory delete failed: {e}")
            return False

    def get_memory_context(self, query: str | None = None, user_id: str | None = None) -> str:
        """
        Get memory context for prompt injection.

        Uses semantic search when a query is available (the normal case),
        otherwise falls back to returning recent memories.
        """
        if query:
            result = self.search(query, user_id=user_id, limit=8)
            if result.memories:
                context = result.to_context_string()
                return f"## Relevant Memories (top-k retrieval)\n{context}"

        # Fallback: recent memories
        all_mems = self.get_all(user_id=user_id, limit=10)
        if not all_mems:
            return ""

        lines = [f"- {m.text}" for m in all_mems[:10]]
        return "## Recent Memories\n" + "\n".join(lines)

    # ── Bulk operations ───────────────────────────────────────────────

    def import_from_text(
        self,
        text: str,
        user_id: str | None = None,
        source: str = "import",
        chunk_size: int = 500,
    ) -> int:
        """
        Import text content (e.g., from MEMORY.md) into vector memory.

        Splits text into chunks and stores each one.

        Args:
            text: Raw text content to import.
            user_id: Optional user ID for namespacing.
            source: Source label for metadata.
            chunk_size: Approximate characters per chunk.

        Returns:
            Number of chunks imported.
        """
        chunks = self._split_text(text, chunk_size)
        imported = 0

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk or chunk.startswith("(") or len(chunk) < 10:
                continue  # skip empty/template content

            messages = [{"role": "user", "content": chunk}]
            metadata = {"source": source}
            result = self.add(messages, user_id=user_id, metadata=metadata)
            imported += len(result)

        logger.info(f"Imported {imported} memories from {source}")
        return imported

    def delete_all(self, user_id: str | None = None) -> None:
        """Delete all memories, optionally filtered by user."""
        try:
            if user_id:
                self._mem0.delete_all(user_id=user_id)
            else:
                self._mem0.reset()
        except Exception as e:
            logger.error(f"Memory delete_all failed: {e}")

    # ── Internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _mem0_result_to_item(r) -> MemoryItem:
        """Convert a Mem0 result dict to a MemoryItem."""
        if isinstance(r, dict):
            return MemoryItem(
                id=r.get("id", r.get("memory_id", "")),
                text=r.get("memory", r.get("text", str(r))),
                score=r.get("score", 0.0),
                metadata=r.get("metadata", {}),
            )
        return MemoryItem(id="", text=str(r), metadata={})

    @staticmethod
    def _split_text(text: str, chunk_size: int = 500) -> list[str]:
        """
        Split text into chunks, preferring natural boundaries (headings, blank lines).
        """
        chunks = []
        current: list[str] = []
        current_len = 0

        for line in text.split("\n"):
            # Natural boundary: heading or separator
            is_boundary = line.startswith("## ") or line.strip() == "---"

            if is_boundary and current and current_len > 50:
                chunks.append("\n".join(current))
                current = []
                current_len = 0

            current.append(line)
            current_len += len(line) + 1

            if current_len >= chunk_size:
                chunks.append("\n".join(current))
                current = []
                current_len = 0

        if current:
            chunks.append("\n".join(current))

        return chunks

    @staticmethod
    def _build_llm_config(config) -> dict[str, Any]:
        """Build LLM config dict from MemoryConfig."""
        cfg: dict[str, Any] = {}
        if getattr(config, "llm_model", None):
            cfg["model"] = config.llm_model
        cfg["temperature"] = getattr(config, "llm_temperature", 0.1)
        cfg["max_tokens"] = getattr(config, "llm_max_tokens", 2000)
        if getattr(config, "llm_api_key", None):
            cfg["api_key"] = config.llm_api_key
        if getattr(config, "llm_api_base", None):
            cfg["api_base"] = config.llm_api_base
        return cfg

    @staticmethod
    def _build_embedder_config(config) -> dict[str, Any]:
        """Build embedder config dict from MemoryConfig."""
        cfg: dict[str, Any] = {}
        if getattr(config, "embedding_model", None):
            cfg["model"] = config.embedding_model
        if getattr(config, "embedder_api_key", None):
            cfg["api_key"] = config.embedder_api_key
        return cfg

    @staticmethod
    def _get_extraction_prompt() -> str:
        """Custom prompt for Mem0's memory extraction, tuned for nanobot."""
        return """You are a memory extraction assistant for an AI agent called nanobot.

Analyze the conversation and extract important information that should be remembered long-term.

Focus on:
1. User preferences (communication style, tools, languages, coding practices)
2. Personal facts (name, role, projects, team members)
3. Project context (tech stack, architecture decisions, goals)
4. Task outcomes and decisions made
5. Recurring patterns or workflows

Do NOT store:
- Trivial chitchat or greetings
- Temporary/ephemeral information (e.g., "it's raining today")
- Sensitive data (passwords, API keys, tokens)
- Information already stored in memory

Return extracted memories as a JSON list. Each memory should be a concise, self-contained fact.
"""
