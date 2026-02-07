"""Memory system for persistent agent memory.

Provides:
- MemoryManager: Main orchestrator for all memory operations
- MemoryIndex: Fast lookup index for memories
- WorkingMemory: In-memory context for current session
- ImportanceScorer: Scores memories based on importance
- KeywordRetriever: Retrieves memories by keyword matching
- TagRetriever: Retrieves memories by tags
"""

from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any
import json
import re

from loguru import logger

from nanobot.utils.helpers import ensure_dir, today_date


@dataclass
class Memory:
    """A single memory entry."""
    id: str
    content: str
    importance: float
    tags: list[str] = field(default_factory=list)
    layer: str = "long-term"  # working, short-term, long-term, skill
    source: str = "conversation"
    section: str = "Important Facts"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_index_entry(self) -> dict:
        """Convert to index entry format."""
        return {
            "id": self.id,
            "content": self.content,
            "content_preview": self.content[:100] + "..." if len(self.content) > 100 else self.content,
            "tags": self.tags,
            "importance": self.importance,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "section": self.section,
            "source": self.source
        }


class MemoryIndex:
    """In-memory index with JSON persistence for fast memory lookup."""

    def __init__(self, index_file: Path):
        self.index_file = Path(index_file)
        self.memories: dict[str, Memory] = {}
        self.keywords: dict[str, list[str]] = {}
        self.tags: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        """Load index from file."""
        if self.index_file.exists():
            try:
                data = json.loads(self.index_file.read_text(encoding="utf-8"))
                for entry in data.get("memories", []):
                    memory = Memory(
                        id=entry["id"],
                        content=entry["content"],
                        importance=entry["importance"],
                        tags=entry.get("tags", []),
                        layer=entry.get("layer", "long-term"),
                        section=entry.get("section", "Important Facts"),
                        created_at=datetime.fromisoformat(entry["created_at"]),
                        updated_at=datetime.fromisoformat(entry["updated_at"])
                    )
                    self.memories[memory.id] = memory
                    self._add_to_indexes(memory)
            except Exception as e:
                logger.error(f"Failed to load memory index: {e}")

    def save(self) -> None:
        """Save index to file."""
        data = {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "memories": [m.to_index_entry() for m in self.memories.values()]
        }
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add(self, memory: Memory) -> None:
        """Add a memory to the index."""
        self.memories[memory.id] = memory
        self._add_to_indexes(memory)
        self.save()

    def remove(self, memory_id: str) -> None:
        """Remove a memory from the index."""
        if memory_id in self.memories:
            memory = self.memories[memory_id]
            self._remove_from_indexes(memory)
            del self.memories[memory_id]
            self.save()

    def update(self, memory: Memory) -> None:
        """Update a memory in the index."""
        if memory.id in self.memories:
            self._remove_from_indexes(self.memories[memory.id])
            self._add_to_indexes(memory)
            self.save()

    def get_memory(self, memory_id: str) -> Memory | None:
        """Get a memory by ID."""
        return self.memories.get(memory_id)

    def get_memories_by_tags(
        self,
        tags: list[str],
        min_importance: float = 0.0,
        limit: int = 20
    ) -> list[Memory]:
        """Get memories that have any of the specified tags."""
        results = []
        for tag in tags:
            if tag in self.tags:
                for memory_id in self.tags[tag]:
                    memory = self.memories.get(memory_id)
                    if memory and memory.importance >= min_importance:
                        if memory.id not in [r.id for r in results]:
                            results.append(memory)
        return results[:limit]

    def lookup(self, keywords: list[str], limit: int = 20) -> list[Memory]:
        """Lookup memories by keywords."""
        results = []
        for keyword in keywords:
            keyword_lower = keyword.lower()
            for kw, memory_ids in self.keywords.items():
                if keyword_lower in kw.lower():
                    for memory_id in memory_ids:
                        memory = self.memories.get(memory_id)
                        if memory:
                            if memory.id not in [r.id for r in results]:
                                results.append(memory)

        # Sort by importance
        results.sort(key=lambda m: m.importance, reverse=True)
        return results[:limit]

    def rebuild(self) -> None:
        """Rebuild index from MEMORY.md file."""
        self.memories = {}
        self.keywords = {}
        self.tags = {}

        # Parse MEMORY.md for memories
        memory_file = self.index_file.parent / "MEMORY.md"
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            # Extract [mem_XXX] entries
            pattern = r'\[(mem_\d+)\]\s*(.+?)(?=\n\[|\n##|\n*$|\n---)'
            for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                memory_id, memory_content = match.groups()
                memory_content = memory_content.strip()

                # Estimate importance based on content
                importance = _estimate_importance(memory_content)
                tags = _extract_tags(memory_content)

                memory = Memory(
                    id=memory_id,
                    content=memory_content,
                    importance=importance,
                    tags=tags,
                    layer="long-term"
                )
                self.memories[memory.id] = memory
                self._add_to_indexes(memory)

        self.save()

    @property
    def all_memories(self) -> list[Memory]:
        """Get all memories sorted by importance."""
        return sorted(self.memories.values(), key=lambda m: m.importance, reverse=True)

    def _add_to_indexes(self, memory: Memory) -> None:
        """Add memory to keyword and tag indexes."""
        # Add to tag index
        for tag in memory.tags:
            if tag not in self.tags:
                self.tags[tag] = []
            if memory.id not in self.tags[tag]:
                self.tags[tag].append(memory.id)

        # Add keywords to index
        keywords = _extract_keywords(memory.content)
        for keyword in keywords:
            if keyword not in self.keywords:
                self.keywords[keyword] = []
            if memory.id not in self.keywords[keyword]:
                self.keywords[keyword].append(memory.id)

    def _remove_from_indexes(self, memory: Memory) -> None:
        """Remove memory from keyword and tag indexes."""
        for tag in memory.tags:
            if tag in self.tags and memory.id in self.tags[tag]:
                self.tags[tag].remove(memory.id)
                if not self.tags[tag]:
                    del self.tags[tag]

        keywords = _extract_keywords(memory.content)
        for keyword in keywords:
            if keyword in self.keywords and memory.id in self.keywords[keyword]:
                self.keywords[keyword].remove(memory.id)
                if not self.keywords[keyword]:
                    del self.keywords[keyword]


class ImportanceScorer:
    """Score memories based on importance."""

    # Keywords that indicate importance
    IMPORTANT_KEYWORDS = {
        "always", "never", "must", "shouldn't", "prefer", "hate",
        "favorite", "worst", "best", "allergic", "cannot", "can't"
    }

    # Patterns that suggest memory-worthy content
    PATTERNS = [
        (r"remember (that|to)", 0.7),
        (r"don't forget", 0.8),
        (r"important", 0.6),
        (r"note that", 0.5),
        (r"user (is|has|works)", 0.7),
        (r"prefers?", 0.6),
    ]

    def score(self, content: str, context: dict | None = None) -> float:
        """
        Calculate importance score (0.0 to 1.0).

        Args:
            content: The potential memory content
            context: Additional context (user message, response, etc.)

        Returns:
            Importance score between 0 and 1
        """
        context = context or {}
        score = 0.3  # Base score

        content_lower = content.lower()

        # Check for importance keywords
        if any(kw in content_lower for kw in self.IMPORTANT_KEYWORDS):
            score += 0.3

        # Check patterns
        for pattern, bonus in self.PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                score += bonus

        # Context factors
        if context.get("is_user_fact", False):
            score += 0.2
        if context.get("is_repeated", False):
            score += 0.1

        # Cap at 1.0
        return min(score, 1.0)


class WorkingMemory:
    """In-memory working memory for current processing cycle."""

    def __init__(self):
        self.recent_memories: list[Memory] = []
        self.current_context: dict = {}
        self.importance_threshold: float = 0.5

    def add(self, memory: Memory) -> None:
        """Add memory to working memory."""
        if memory.importance >= self.importance_threshold:
            self.recent_memories.append(memory)
            # Keep only last 10
            self.recent_memories = self.recent_memories[-10:]

    def get_all(self) -> list[Memory]:
        """Get all working memories."""
        return self.recent_memories.copy()

    def clear(self) -> None:
        """Clear working memory after processing."""
        self.recent_memories = []


class KeywordRetriever:
    """Retrieve memories by keyword matching."""

    def __init__(self, index: MemoryIndex):
        self.index = index

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.2
    ) -> list[Memory]:
        """Retrieve memories matching query keywords."""
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        results = self.index.lookup(keywords, limit * 2)

        # Filter by minimum score
        filtered = [m for m in results if m.importance >= min_score]
        return filtered[:limit]

    def _extract_keywords(self, query: str) -> list[str]:
        """Extract keywords from query."""
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "do", "does",
                     "i", "you", "he", "she", "it", "we", "they", "what", "how",
                     "why", "when", "where", "which", "who", "whom", "this",
                     "that", "these", "those", "to", "of", "in", "for", "on",
                     "with", "at", "by", "from", "as", "into", "through"}
        words = re.findall(r'\b[a-z]+\b', query.lower())
        return [w for w in words if w not in stopwords and len(w) > 2]


class TagRetriever:
    """Retrieve memories by tags."""

    def __init__(self, index: MemoryIndex):
        self.index = index

    def retrieve(
        self,
        tags: list[str],
        min_importance: float = 0.0,
        limit: int = 20
    ) -> list[Memory]:
        """Get all memories with any of the specified tags."""
        return self.index.get_memories_by_tags(tags, min_importance, limit)


class MemoryManager:
    """
    Main memory management class.

    Provides:
    - Memory reading and writing
    - Retrieval by keywords, tags, time
    - Index management
    - Integration with agent loop

    Backward compatible with existing MemoryStore API.
    """

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.memory_dir = ensure_dir(self.workspace / "memory")
        self.daily_dir = ensure_dir(self.memory_dir / "daily")
        self.archive_dir = ensure_dir(self.memory_dir / "archives")

        # Memory files
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.index_file = self.memory_dir / "index.json"

        # Initialize index
        self.index = MemoryIndex(self.index_file)

        # Initialize retrievers
        self.keyword_retriever = KeywordRetriever(self.index)
        self.tag_retriever = TagRetriever(self.index)

        # Initialize components
        self.scorer = ImportanceScorer()
        self.working_memory = WorkingMemory()

        # Initialize default MEMORY.md if needed
        self._ensure_memory_file()

    def _ensure_memory_file(self) -> None:
        """Ensure MEMORY.md file exists with header."""
        if not self.memory_file.exists():
            header = """# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

(Important facts about the user)

## Preferences

(User preferences learned over time)

## Project Context

(Information about ongoing projects)

## Skills & Tools

(Knowledge about tool usage patterns)

## Important Facts

(High-importance persistent information)

---

*This file is automatically managed by nanobot.*
"""
            self.memory_file.write_text(header, encoding="utf-8")

    # ==================== Reading (Backward Compatible) ====================

    def get_today_file(self) -> Path:
        """Get path to today's memory file."""
        return self.daily_dir / f"{today_date()}.md"

    def read_today(self) -> str:
        """Read today's daily notes."""
        today_file = self.get_today_file()
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""

    def read_long_term(self) -> str:
        """Read long-term memory (MEMORY.md)."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def read(self) -> str:
        """Read long-term memory (alias for backward compatibility)."""
        return self.read_long_term()

    def get_recent_memories(self, days: int = 7) -> str:
        """Get memories from the last N days."""
        memories = []
        today = datetime.now().date()

        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            file_path = self.daily_dir / f"{date_str}.md"

            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                memories.append(content)

        return "\n\n---\n\n".join(memories)

    # ==================== Writing ====================

    def write_memory(
        self,
        content: str,
        section: str = "Important Facts",
        importance: float | None = None,
        tags: list[str] | None = None
    ) -> Memory:
        """Write a new memory to long-term storage.

        Args:
            content: The memory content
            section: Section in MEMORY.md to write to
            importance: Optional importance score (auto-calculated if not provided)
            tags: Optional tags for the memory

        Returns:
            The created Memory object
        """
        memory_id = self._generate_id()

        # Calculate importance if not provided
        calc_importance = importance
        if calc_importance is None:
            calc_importance = self.scorer.score(content, {})

        # Extract tags if not provided
        calc_tags = tags if tags is not None else _extract_tags(content)

        memory = Memory(
            id=memory_id,
            content=content,
            importance=calc_importance,
            tags=calc_tags,
            layer="long-term",
            section=section
        )

        # Write to MEMORY.md
        entry = f"[{memory_id}] {content}"
        self._append_to_memory_file(entry, section)

        # Add to index
        self.index.add(memory)

        logger.info(f"Wrote memory {memory_id} to section '{section}' (importance: {calc_importance:.2f})")
        return memory

    def append_to_today(self, content: str) -> None:
        """Append content to today's daily notes."""
        today_file = self.get_today_file()

        if today_file.exists():
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n\n" + content
        else:
            header = f"# {today_date()}\n\n"
            content = header + content

        today_file.write_text(content, encoding="utf-8")

    def append_today(self, content: str) -> None:
        """Backward compatible alias for append_to_today."""
        self.append_to_today(content)

    # ==================== Retrieval ====================

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        min_importance: float = 0.3
    ) -> list[Memory]:
        """Retrieve relevant memories for a query."""
        return self.keyword_retriever.retrieve(query, limit, min_importance)

    def retrieve_by_tags(
        self,
        tags: list[str],
        min_importance: float = 0.0,
        limit: int = 20
    ) -> list[Memory]:
        """Retrieve memories by tags."""
        return self.tag_retriever.retrieve(tags, min_importance, limit)

    def get_recent(self, days: int = 7, min_importance: float = 0.5) -> list[Memory]:
        """Get memories from the last N days by importance."""
        cutoff = datetime.now() - timedelta(days=days)
        memories = []

        for memory in self.index.all_memories:
            if memory.updated_at >= cutoff:
                if memory.importance >= min_importance:
                    memories.append(memory)

        return sorted(memories, key=lambda m: m.updated_at, reverse=True)

    def get_memory_by_id(self, memory_id: str) -> Memory | None:
        """Get a memory by its ID."""
        return self.index.get_memory(memory_id)

    # ==================== Skill Memory ====================

    def get_skill_memories(self, skill_name: str) -> list[Memory]:
        """Get memories for a specific skill."""
        skill_memory_dir = self.workspace / "skills" / skill_name / "memory"
        memory_file = skill_memory_dir / "context.md"

        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            return [Memory(
                id=f"skill_{skill_name}",
                content=content,
                importance=0.8,
                tags=["skill", skill_name],
                layer="skill",
                source=skill_name
            )]

        return []

    def write_skill_memory(self, skill_name: str, content: str) -> None:
        """Write memory for a specific skill."""
        skill_memory_dir = ensure_dir(self.workspace / "skills" / skill_name / "memory")
        memory_file = skill_memory_dir / "context.md"
        memory_file.write_text(content, encoding="utf-8")

    # ==================== Context Building ====================

    def get_memory_context(
        self,
        query: str = "",
        max_tokens: int = 8000
    ) -> str:
        """
        Get formatted memory context for LLM.

        Combines:
        - Retrieved relevant memories
        - Today's notes summary
        - Skill memories if relevant

        Args:
            query: Query to match memories against
            max_tokens: Maximum tokens for context

        Returns:
            Formatted memory context string
        """
        memories = []

        # Retrieve relevant memories
        if query:
            retrieved = self.retrieve(query, limit=20, min_importance=0.3)
            memories.extend(retrieved)

        # Add today's notes (always include summary)
        today = self.read_today()
        if today:
            summary = self._summarize_today(today)
            memories.append(Memory(
                id="today_notes",
                content=summary,
                importance=0.8,
                tags=["daily", "notes"],
                layer="short-term",
                source="daily"
            ))

        # Add skill memories if relevant
        skill_names = self._detect_skills(query)
        for skill in skill_names:
            skill_memories = self.get_skill_memories(skill)
            memories.extend(skill_memories)

        # Sort by importance
        memories.sort(key=lambda m: m.importance, reverse=True)

        # Format
        return self._format_memories(memories, max_tokens)

    def get_context(self) -> str:
        """Backward compatible alias for get_memory_context."""
        return self.get_memory_context()

    # ==================== Maintenance ====================

    def rebuild_index(self) -> None:
        """Rebuild memory index from MEMORY.md."""
        self.index.rebuild()
        logger.info(f"Rebuilt memory index with {len(self.index.memories)} memories")

    def archive_old_memories(self, older_than_days: int = 90) -> int:
        """Archive memories older than specified days.

        Args:
            older_than_days: Archive memories older than this many days

        Returns:
            Number of memories archived
        """
        cutoff = datetime.now() - timedelta(days=older_than_days)
        archived = 0

        for memory in list(self.index.memories.values()):
            if memory.created_at < cutoff:
                self._archive_memory(memory, reason="age")
                archived += 1

        return archived

    def delete_memory(self, memory_id: str) -> bool:
        """Permanently delete a memory (use archive() for soft delete).

        Args:
            memory_id: The memory ID to delete

        Returns:
            True if deleted, False if not found
        """
        memory = self.index.get_memory(memory_id)
        if not memory:
            return False

        # Remove from MEMORY.md (mark as deleted)
        self._remove_from_memory_file(memory_id)

        # Remove from index
        self.index.remove(memory_id)

        logger.info(f"Deleted memory {memory_id}")
        return True

    def archive_memory(self, memory_id: str, reason: str = "manual") -> bool:
        """Archive (soft delete) a memory.

        Args:
            memory_id: The memory ID to archive
            reason: Reason for archiving

        Returns:
            True if archived, False if not found
        """
        memory = self.index.get_memory(memory_id)
        if not memory:
            return False

        self._archive_memory(memory, reason)
        return True

    def _archive_memory(self, memory: Memory, reason: str) -> None:
        """Internal method to archive a memory."""
        archive_path = ensure_dir(self.archive_dir / datetime.now().strftime("%Y-%m")) / f"{memory.id}.json"

        archive_data = {
            "id": memory.id,
            "content": memory.content,
            "importance": memory.importance,
            "tags": memory.tags,
            "layer": memory.layer,
            "section": memory.section,
            "archived_at": datetime.now().isoformat(),
            "reason": reason
        }

        archive_path.write_text(json.dumps(archive_data, indent=2), encoding="utf-8")

        # Remove from active index
        self.index.remove(memory.id)

        logger.info(f"Archived memory {memory.id} with reason: {reason}")

    # ==================== Utilities ====================

    def generate_id(self) -> str:
        """Generate next memory ID."""
        return self._generate_id()

    def stats(self) -> dict[str, Any]:
        """Get memory statistics.

        Returns:
            Dictionary with memory statistics
        """
        all_memories = self.index.all_memories
        return {
            "total_memories": len(all_memories),
            "avg_importance": sum(m.importance for m in all_memories) / len(all_memories) if all_memories else 0,
            "by_importance": {
                "high (>=0.7)": len([m for m in all_memories if m.importance >= 0.7]),
                "medium (0.4-0.7)": len([m for m in all_memories if 0.4 <= m.importance < 0.7]),
                "low (<0.4)": len([m for m in all_memories if m.importance < 0.4])
            },
            "tags": list(self.index.tags.keys()),
            "index_size": len(self.index.memories)
        }

    # ==================== Internal Helpers ====================

    def _generate_id(self) -> str:
        """Generate next memory ID."""
        existing_ids = set(self.index.memories.keys())
        num = 1
        while f"mem_{num:03d}" in existing_ids:
            num += 1
        return f"mem_{num:03d}"

    def _append_to_memory_file(self, entry: str, section: str) -> None:
        """Append entry to MEMORY.md in correct section."""
        content = self.read_long_term()

        # Find section and append
        section_pattern = rf'## {re.escape(section)}\n'
        match = re.search(section_pattern, content)

        if match:
            # Find end of section (next ## or end of file)
            start = match.end()
            next_section = re.search(r'\n## ', content[start:])
            if next_section:
                end = start + next_section.start()
            else:
                end = len(content)

            # Insert entry before next section or at end
            new_content = content[:end] + f"\n{entry}" + content[end:]
        else:
            # Section doesn't exist, append before footer
            footer = content.rfind("\n---")
            if footer != -1:
                new_content = content[:footer] + f"\n\n## {section}\n\n{entry}\n" + content[footer:]
            else:
                new_content = content + f"\n\n## {section}\n\n{entry}"

        self.memory_file.write_text(new_content, encoding="utf-8")

    def _remove_from_memory_file(self, memory_id: str) -> None:
        """Remove a memory entry from MEMORY.md."""
        content = self.read_long_term()
        # Remove [mem_XXX] entry and following newlines
        pattern = rf'\[{memory_id}\][^\[]*?(?=\n\[|\n##|\n---|\n*$)'
        new_content = re.sub(pattern, '', content, flags=re.MULTILINE | re.DOTALL)
        self.memory_file.write_text(new_content, encoding="utf-8")

    def _format_memories(self, memories: list[Memory], max_tokens: int) -> str:
        """Format memories for LLM context."""
        if not memories:
            return ""

        parts = ["# Relevant Memories\n"]

        for memory in memories:
            importance_bar = "█" * int(memory.importance * 5)
            parts.append(f"- *[{memory.id}]* {memory.content}")
            parts.append(f"  - importance: {memory.importance:.1f}, tags: {', '.join(memory.tags) if memory.tags else 'none'}")

        result = "\n".join(parts)

        # Rough token estimation (4 chars per token)
        if len(result) > max_tokens * 4:
            result = result[:max_tokens * 4] + "... (truncated)"

        return result

    def _summarize_today(self, content: str) -> str:
        """Summarize today's notes for context."""
        if not content:
            return ""

        # Remove header if present
        lines = content.split("\n")
        if lines and lines[0].startswith("# "):
            lines = lines[1:]

        content = "\n".join(lines).strip()
        if len(content) < 500:
            return content

        # Take first paragraph
        first_para = content.split("\n\n")[0]
        return first_para[:500] + ("..." if len(first_para) > 500 else "")

    def _detect_skills(self, query: str) -> list[str]:
        """Detect which skills might be relevant to the query."""
        skills_path = self.workspace / "skills"
        if not skills_path.exists():
            return []

        skills = []
        query_lower = query.lower()

        for skill_dir in skills_path.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                skill_name = skill_dir.name
                # Check if skill name appears in query
                if skill_name.lower() in query_lower:
                    skills.append(skill_name)

        return skills


# ==================== Helper Functions ====================

def _extract_keywords(content: str) -> list[str]:
    """Extract keywords from content for indexing."""
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                 "being", "have", "has", "had", "do", "does", "did", "will",
                 "would", "could", "should", "may", "might", "must", "shall",
                 "can", "need", "dare", "ought", "used", "to", "of", "in",
                 "for", "on", "with", "at", "by", "from", "as", "into",
                 "through", "during", "before", "after", "above", "below",
                 "between", "under", "again", "further", "then", "once",
                 "i", "you", "he", "she", "it", "we", "they", "what", "how",
                 "why", "when", "where", "which", "who", "whom", "this",
                 "that", "these", "those"}

    words = re.findall(r'\b[a-z]+\b', content.lower())
    return [w for w in words if w not in stopwords and len(w) > 2]


def _extract_tags(content: str) -> list[str]:
    """Extract tags from content."""
    tags = []

    # Look for #tag format
    tags.extend(re.findall(r'#(\w+)', content))

    # Infer tags based on content
    content_lower = content.lower()

    if "user" in content_lower or "name" in content_lower or "call" in content_lower:
        tags.append("user")
    if "prefer" in content_lower or "like" in content_lower or "dislike" in content_lower:
        tags.append("preference")
    if "project" in content_lower or "working" in content_lower:
        tags.append("project")
    if "skill" in content_lower or "tool" in content_lower or "command" in content_lower:
        tags.append("skill")
    if "remember" in content_lower or "important" in content_lower:
        tags.append("important")

    return list(set(tags))


def _estimate_importance(content: str) -> float:
    """Estimate importance from content (for rebuild)."""
    scorer = ImportanceScorer()
    return scorer.score(content, {})


# ==================== Backward Compatibility ====================

class MemoryStore(MemoryManager):
    """Backward compatible alias for MemoryManager.

    All existing code using MemoryStore will continue to work.
    """

    def __init__(self, workspace: Path):
        super().__init__(workspace)
        logger.info("Using MemoryManager (MemoryStore compatibility mode)")


# ==================== Tools ====================

class RememberTool:
    """Tool to explicitly store a memory."""

    name = "remember"
    description = "Store important information for later recall"

    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The information to remember"
            },
            "importance": {
                "type": "number",
                "description": "Importance score (0-1), default 0.7",
                "default": 0.7
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for categorization",
                "default": []
            }
        },
        "required": ["content"]
    }

    def __init__(self, memory_manager: MemoryManager):
        self.memory = memory_manager

    async def execute(self, content: str, importance: float = 0.7, tags: list[str] | None = None) -> dict:
        """Execute the remember tool."""
        memory = self.memory.write_memory(
            content=content,
            importance=importance,
            tags=tags or []
        )
        return {
            "success": True,
            "memory_id": memory.id,
            "output": f"Remembered: [{memory.id}] {content[:100]}...",
            "importance": memory.importance
        }


class RecallTool:
    """Tool to recall memories."""

    name = "recall"
    description = "Recall relevant memories based on a query"

    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Query to search memories"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter by tags"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum memories to return",
                "default": 5
            }
        },
        "required": ["query"]
    }

    def __init__(self, memory_manager: MemoryManager):
        self.memory = memory_manager

    async def execute(self, query: str, tags: list[str] | None = None, limit: int = 5) -> dict:
        """Execute the recall tool."""
        if tags:
            memories = self.memory.retrieve_by_tags(tags, limit=limit)
        else:
            memories = self.memory.retrieve(query, limit=limit)

        if not memories:
            return {
                "success": True,
                "memories": [],
                "output": "No relevant memories found."
            }

        formatted = "\n".join([
            f"[{m.id}] {m.content} (importance: {m.importance})"
            for m in memories
        ])

        return {
            "success": True,
            "memories": [
                {"id": m.id, "content": m.content, "importance": m.importance, "tags": m.tags}
                for m in memories
            ],
            "output": formatted
        }


class ForgetTool:
    """Tool to remove a memory."""

    name = "forget"
    description = "Remove a specific memory from storage"

    parameters = {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "string",
                "description": "The memory ID to remove (e.g., mem_001)"
            },
            "reason": {
                "type": "string",
                "description": "Reason for forgetting"
            }
        },
        "required": ["memory_id"]
    }

    def __init__(self, memory_manager: MemoryManager):
        self.memory = memory_manager

    async def execute(self, memory_id: str, reason: str = "manual") -> dict:
        """Execute the forget tool."""
        success = self.memory.archive_memory(memory_id, reason)
        if success:
            return {
                "success": True,
                "output": f"Archived memory {memory_id}"
            }
        return {
            "success": False,
            "error": f"Memory {memory_id} not found"
        }
