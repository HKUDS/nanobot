"""Filesystem-based memory provider (default implementation)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.memory.base import BaseMemoryProvider, MemoryEntry
from nanobot.utils.helpers import ensure_dir


class FilesystemMemoryProvider(BaseMemoryProvider):
    """Default filesystem-based memory provider.
    
    Stores memory in two files:
    - MEMORY.md: Long-term facts and preferences (markdown)
    - HISTORY.md: Append-only event log (plain text with timestamps)
    
    This is the default implementation that maintains backward compatibility
    with nanobot's original memory system.
    
    Configuration:
        workspace: Base directory for memory storage
        memory_dir: Subdirectory name (default: "memory")
        memory_file: Long-term memory filename (default: "MEMORY.md")
        history_file: History filename (default: "HISTORY.md")
    
    Example:
        provider = FilesystemMemoryProvider({
            "workspace": "/home/user/.nanobot/workspace",
            "memory_dir": "memory",
        })
        
        provider.write_long_term("# User Preferences\n\nLikes dark mode.")
        provider.append_history("[2024-01-15 10:30] Started new project: nanobot")
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the filesystem memory provider.
        
        Args:
            config: Configuration dictionary with keys:
                - workspace (required): Base directory path
                - memory_dir: Memory subdirectory (default: "memory")
                - memory_file: Long-term memory file (default: "MEMORY.md")
                - history_file: History file (default: "HISTORY.md")
        """
        super().__init__(config)
        
        workspace = self.config.get("workspace")
        if not workspace:
            raise ValueError("FilesystemMemoryProvider requires 'workspace' in config")
        
        self._workspace = Path(workspace).expanduser()
        memory_dir_name = self.config.get("memory_dir", "memory")
        self._memory_dir = ensure_dir(self._workspace / memory_dir_name)
        
        self._memory_file = self._memory_dir / self.config.get("memory_file", "MEMORY.md")
        self._history_file = self._memory_dir / self.config.get("history_file", "HISTORY.md")

    @property
    def name(self) -> str:
        """Return provider name."""
        return "filesystem"

    def read_long_term(self) -> str:
        """Read the full long-term memory content.
        
        Returns:
            Content of MEMORY.md or empty string if file doesn't exist.
        """
        if self._memory_file.exists():
            return self._memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """Write the full long-term memory content.
        
        Args:
            content: Complete long-term memory as markdown.
        """
        self._memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        """Append an entry to the history log.
        
        Args:
            entry: History entry text (typically with [YYYY-MM-DD HH:MM] prefix).
        """
        with open(self._history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def search_history(
        self,
        query: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[MemoryEntry]:
        """Search history entries.
        
        This is a simple in-memory search for the filesystem provider.
        For production use with large history, consider using a database provider.
        
        Args:
            query: Optional text to search for (case-insensitive)
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Maximum entries to return
            
        Returns:
            List of matching MemoryEntry objects, newest first.
        """
        if not self._history_file.exists():
            return []

        entries = []
        content = self._history_file.read_text(encoding="utf-8")
        
        # Split by double newlines (entry separator)
        raw_entries = content.split("\n\n")
        
        for raw_entry in raw_entries:
            raw_entry = raw_entry.strip()
            if not raw_entry:
                continue

            # Try to parse timestamp from [YYYY-MM-DD HH:MM] format
            timestamp = None
            entry_content = raw_entry
            
            if raw_entry.startswith("[") and "]" in raw_entry:
                time_str = raw_entry[1:raw_entry.find("]")]
                try:
                    timestamp = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                    entry_content = raw_entry[raw_entry.find("]") + 1:].strip()
                except ValueError:
                    pass
            
            if timestamp is None:
                timestamp = datetime.now()  # Fallback

            # Apply filters
            if start_time and timestamp < start_time:
                continue
            if end_time and timestamp > end_time:
                continue
            if query and query.lower() not in raw_entry.lower():
                continue

            entries.append(MemoryEntry(
                content=entry_content,
                timestamp=timestamp,
                entry_type="history",
            ))

        # Sort by timestamp (newest first) and limit
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit]

    def get_memory_context(self) -> str:
        """Get formatted memory context for LLM prompts.
        
        Returns:
            Long-term memory with header, or empty string if no memory.
        """
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    @property
    def memory_file(self) -> Path:
        """Path to the long-term memory file."""
        return self._memory_file

    @property
    def history_file(self) -> Path:
        """Path to the history file."""
        return self._history_file

    @property
    def is_available(self) -> bool:
        """Check if the provider is available.
        
        Returns:
            True if the memory directory is writable.
        """
        try:
            # Try to create directory and write test file
            self._memory_dir.mkdir(parents=True, exist_ok=True)
            test_file = self._memory_dir / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            return True
        except Exception:
            return False


# Register the provider
from nanobot.memory.registry import MemoryProviderRegistry
MemoryProviderRegistry.register("filesystem", FilesystemMemoryProvider)
