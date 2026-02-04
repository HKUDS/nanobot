"""
Core Memory System - Memories that are never forgotten.

Core memories are:
1. Pinned facts that survive compaction
2. User preferences and identity info
3. Important decisions and patterns
4. Loaded from SOUL.md and CORE.json
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CoreMemory:
    """A single core memory entry."""

    id: str
    content: str
    category: str  # identity, preference, decision, fact, pattern
    created_at: str
    importance: int = 5  # 1-10, higher = more important
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "created_at": self.created_at,
            "importance": self.importance,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CoreMemory":
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            category=data.get("category", "fact"),
            created_at=data.get("created_at", ""),
            importance=data.get("importance", 5),
            metadata=data.get("metadata", {}),
        )


class CoreMemoryStore:
    """
    Manages core memories that persist across conversations.

    Core memories are stored in:
    - SOUL.md: Human-readable identity/personality (loaded into context)
    - CORE.json: Machine-readable facts and preferences
    """

    CATEGORIES = ["identity", "preference", "decision", "fact", "pattern", "user"]

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_dir = workspace / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.soul_file = workspace / "memory" / "SOUL.md"
        self.core_file = workspace / "memory" / "CORE.json"

        self._memories: dict[str, CoreMemory] = {}
        self._load()

    def _load(self) -> None:
        """Load core memories from CORE.json."""
        if self.core_file.exists():
            try:
                data = json.loads(self.core_file.read_text(encoding="utf-8"))
                for item in data.get("memories", []):
                    mem = CoreMemory.from_dict(item)
                    self._memories[mem.id] = mem
                logger.debug(f"Loaded {len(self._memories)} core memories")
            except Exception as e:
                logger.warning(f"Failed to load core memories: {e}")

    def _save(self) -> None:
        """Save core memories to CORE.json."""
        try:
            data = {
                "version": 1,
                "updated_at": datetime.now().isoformat(),
                "memories": [m.to_dict() for m in self._memories.values()]
            }
            self.core_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Failed to save core memories: {e}")

    def add(
        self,
        content: str,
        category: str = "fact",
        importance: int = 5,
        metadata: Optional[dict] = None
    ) -> CoreMemory:
        """
        Add a new core memory.

        Args:
            content: The memory content
            category: Category (identity, preference, decision, fact, pattern, user)
            importance: 1-10 importance score
            metadata: Optional metadata

        Returns:
            The created CoreMemory
        """
        if category not in self.CATEGORIES:
            category = "fact"

        mem_id = f"core_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{len(self._memories)}"

        memory = CoreMemory(
            id=mem_id,
            content=content,
            category=category,
            created_at=datetime.now().isoformat(),
            importance=max(1, min(10, importance)),
            metadata=metadata or {}
        )

        self._memories[mem_id] = memory
        self._save()

        logger.info(f"Added core memory: {mem_id} ({category})")
        return memory

    def remove(self, memory_id: str) -> bool:
        """Remove a core memory by ID."""
        if memory_id in self._memories:
            del self._memories[memory_id]
            self._save()
            logger.info(f"Removed core memory: {memory_id}")
            return True
        return False

    def get(self, memory_id: str) -> Optional[CoreMemory]:
        """Get a core memory by ID."""
        return self._memories.get(memory_id)

    def list(self, category: Optional[str] = None) -> list[CoreMemory]:
        """
        List core memories, optionally filtered by category.

        Returns memories sorted by importance (descending).
        """
        memories = list(self._memories.values())

        if category:
            memories = [m for m in memories if m.category == category]

        return sorted(memories, key=lambda m: m.importance, reverse=True)

    def search(self, query: str) -> list[CoreMemory]:
        """
        Search core memories by content.

        Simple keyword search for now.
        """
        query_lower = query.lower()
        matches = []

        for mem in self._memories.values():
            if query_lower in mem.content.lower():
                matches.append(mem)

        return sorted(matches, key=lambda m: m.importance, reverse=True)

    def get_soul(self) -> str:
        """
        Get the SOUL.md content (human-readable identity).

        Returns empty string if not found.
        """
        if self.soul_file.exists():
            return self.soul_file.read_text(encoding="utf-8")
        return ""

    def update_soul(self, content: str) -> None:
        """Update SOUL.md content."""
        self.soul_file.write_text(content, encoding="utf-8")
        logger.info("Updated SOUL.md")

    def get_context(self, max_chars: int = 4000) -> str:
        """
        Get core memories formatted for context injection.

        Includes:
        1. SOUL.md content
        2. High-importance core memories from CORE.json

        Args:
            max_chars: Maximum characters to return

        Returns:
            Formatted string for system prompt
        """
        parts = []
        total_chars = 0

        # Soul first (always included)
        soul = self.get_soul()
        if soul:
            parts.append(soul)
            total_chars += len(soul)

        # Add core memories by importance
        memories = self.list()
        if memories:
            mem_lines = ["\n## Core Memories\n"]

            for mem in memories:
                if mem.importance < 3:
                    continue  # Skip low importance

                line = f"- [{mem.category}] {mem.content}\n"

                if total_chars + len(line) > max_chars:
                    break

                mem_lines.append(line)
                total_chars += len(line)

            if len(mem_lines) > 1:
                parts.append("".join(mem_lines))

        return "\n".join(parts)

    def extract_from_conversation(
        self,
        user_msg: str,
        assistant_msg: str
    ) -> list[dict]:
        """
        Extract potential core memories from a conversation.

        Returns suggestions for memories to potentially add.
        (LLM would be used to actually extract, this is a placeholder)
        """
        suggestions = []

        # Simple heuristics for now
        triggers = {
            "meu nome é": ("user", 8),
            "my name is": ("user", 8),
            "sempre use": ("preference", 7),
            "always use": ("preference", 7),
            "não faça": ("preference", 7),
            "don't do": ("preference", 7),
            "lembre-se": ("fact", 6),
            "remember": ("fact", 6),
            "importante": ("fact", 6),
            "important": ("fact", 6),
        }

        combined = f"{user_msg} {assistant_msg}".lower()

        for trigger, (category, importance) in triggers.items():
            if trigger in combined:
                suggestions.append({
                    "trigger": trigger,
                    "category": category,
                    "importance": importance,
                    "source_user": user_msg,
                    "source_assistant": assistant_msg
                })

        return suggestions


# Global accessor
_store: Optional[CoreMemoryStore] = None


def get_core_memory_store(workspace: Path) -> CoreMemoryStore:
    """Get or create the global core memory store."""
    global _store
    if _store is None or _store.workspace != workspace:
        _store = CoreMemoryStore(workspace)
    return _store
