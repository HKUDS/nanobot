"""
File-based memory store — backward-compatible fallback.

Wraps the original MEMORY.md + daily-notes system behind the BaseMemoryStore
interface so it can be swapped transparently with the vector store.
"""

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from nanobot.memory.base import BaseMemoryStore
from nanobot.memory.types import MemoryItem, MemorySearchResult
from nanobot.utils.helpers import ensure_dir, today_date


class FileMemoryStore(BaseMemoryStore):
    """
    Original file-based memory: MEMORY.md + daily YYYY-MM-DD.md notes.

    Used as fallback when chromadb/mem0 are not installed.
    """

    def __init__(self, workspace: Path):
        super().__init__(workspace)
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"

    # ── BaseMemoryStore interface ──────────────────────────────────────

    def search(self, query: str, user_id: str | None = None, limit: int = 8) -> MemorySearchResult:
        """
        'Search' by returning all file-based memories (no real vector search).

        For file-based storage we can't do semantic search, so we return
        long-term + recent memories as-is.
        """
        items = self._collect_all_items()
        return MemorySearchResult(
            memories=items[:limit],
            query=query,
            total_found=len(items),
        )

    def add(
        self,
        messages: list[dict[str, str]],
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> list[MemoryItem]:
        """
        No-op for file store — the agent writes to MEMORY.md directly via tools.

        The original nanobot design has the LLM use write_file/edit_file to
        update MEMORY.md, so we don't extract memories automatically here.
        """
        return []

    def get_all(self, user_id: str | None = None, limit: int = 100) -> list[MemoryItem]:
        """Return all file-based memory items."""
        return self._collect_all_items()[:limit]

    def delete(self, memory_id: str) -> bool:
        """Not supported for file store."""
        return False

    def get_memory_context(self, query: str | None = None, user_id: str | None = None) -> str:
        """
        Get memory context — original behavior: full MEMORY.md + today's notes.
        """
        parts = []

        long_term = self.read_long_term()
        if long_term:
            parts.append("## Long-term Memory\n" + long_term)

        today = self.read_today()
        if today:
            parts.append("## Today's Notes\n" + today)

        return "\n\n".join(parts) if parts else ""

    # ── Original MemoryStore API (preserved for backward compat) ──────

    def get_today_file(self) -> Path:
        """Get path to today's memory file."""
        return self.memory_dir / f"{today_date()}.md"

    def read_today(self) -> str:
        """Read today's memory notes."""
        today_file = self.get_today_file()
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""

    def append_today(self, content: str) -> None:
        """Append content to today's memory notes."""
        today_file = self.get_today_file()

        if today_file.exists():
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n" + content
        else:
            header = f"# {today_date()}\n\n"
            content = header + content

        today_file.write_text(content, encoding="utf-8")

    def read_long_term(self) -> str:
        """Read long-term memory (MEMORY.md)."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """Write to long-term memory (MEMORY.md)."""
        self.memory_file.write_text(content, encoding="utf-8")

    def get_recent_memories(self, days: int = 7) -> str:
        """Get memories from the last N days."""
        memories = []
        today = datetime.now().date()

        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            file_path = self.memory_dir / f"{date_str}.md"

            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                memories.append(content)

        return "\n\n---\n\n".join(memories)

    def list_memory_files(self) -> list[Path]:
        """List all memory files sorted by date (newest first)."""
        if not self.memory_dir.exists():
            return []

        files = list(self.memory_dir.glob("????-??-??.md"))
        return sorted(files, reverse=True)

    # ── Internal helpers ──────────────────────────────────────────────

    def _collect_all_items(self) -> list[MemoryItem]:
        """Collect all memories as MemoryItem objects."""
        items = []

        # Long-term memory chunks
        long_term = self.read_long_term()
        if long_term:
            for i, chunk in enumerate(self._split_into_chunks(long_term)):
                chunk_text = chunk.strip()
                if chunk_text and not chunk_text.startswith("("):  # skip template placeholders
                    items.append(MemoryItem(
                        id=self._make_id(chunk_text),
                        text=chunk_text,
                        metadata={"source": "memory_md", "type": "long_term"},
                    ))

        # Today's notes
        today = self.read_today()
        if today:
            items.append(MemoryItem(
                id=self._make_id(f"today_{today_date()}"),
                text=today.strip(),
                metadata={"source": "daily_note", "type": "note"},
            ))

        return items

    @staticmethod
    def _split_into_chunks(text: str) -> list[str]:
        """Split markdown text into meaningful chunks by headings or separators."""
        chunks = []
        current = []

        for line in text.split("\n"):
            if line.startswith("## ") or line.strip() == "---":
                if current:
                    chunks.append("\n".join(current))
                    current = []
            current.append(line)

        if current:
            chunks.append("\n".join(current))

        return chunks

    @staticmethod
    def _make_id(text: str) -> str:
        """Create a stable ID from text content."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
