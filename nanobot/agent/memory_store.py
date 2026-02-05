"""Memory system for persistent agent memory."""

from pathlib import Path
from datetime import datetime, timedelta

from nanobot.utils.helpers import ensure_dir, today_date


# Constants for memory size limits
MAX_CONTEXT_TOKENS = 2000  # Maximum tokens for memory context
CHARS_PER_TOKEN = 4  # Approximate characters per token
MAX_CONTEXT_CHARS = MAX_CONTEXT_TOKENS * CHARS_PER_TOKEN
DEFAULT_MEMORY_DAYS = 3  # Reduced from 7 to 3 for efficiency


class MemoryStore:
    """
    Memory system for the agent.
    
    Supports daily notes (memory/YYYY-MM-DD.md) and long-term memory (MEMORY.md).
    """
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
    
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
            # Add header for new day
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
    
    def get_recent_memories(self, days: int = DEFAULT_MEMORY_DAYS) -> str:
        """
        Get memories from the last N days.

        Args:
            days: Number of days to look back (default: 3).

        Returns:
            Combined memory content.
        """
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
    
    def get_memory_context(self, max_chars: int = MAX_CONTEXT_CHARS) -> str:
        """
        Get memory context for the agent with size limits.

        Args:
            max_chars: Maximum characters to return (default: ~2000 tokens).

        Returns:
            Formatted memory context including long-term and recent memories,
            truncated to fit within the size limit.
        """
        parts = []
        remaining_chars = max_chars

        # Long-term memory (prioritized - gets 60% of budget)
        long_term_budget = int(max_chars * 0.6)
        long_term = self.read_long_term()
        if long_term:
            truncated_long_term = self._truncate(long_term, long_term_budget)
            parts.append("## Long-term Memory\n" + truncated_long_term)
            remaining_chars -= len(truncated_long_term)

        # Today's notes (gets remaining budget)
        today = self.read_today()
        if today and remaining_chars > 100:  # Only include if we have space
            truncated_today = self._truncate(today, remaining_chars)
            parts.append("## Today's Notes\n" + truncated_today)

        return "\n\n".join(parts) if parts else ""

    def _truncate(self, content: str, max_chars: int) -> str:
        """
        Truncate content to fit within character limit.

        Attempts to truncate at sentence boundaries when possible.

        Args:
            content: The content to truncate.
            max_chars: Maximum characters allowed.

        Returns:
            Truncated content with ellipsis if truncated.
        """
        if len(content) <= max_chars:
            return content

        # Reserve space for truncation indicator
        truncate_at = max_chars - 20

        # Try to find a good break point (sentence end)
        for sep in ["\n\n", ".\n", ". ", "\n"]:
            pos = content.rfind(sep, 0, truncate_at)
            if pos > truncate_at // 2:  # Only use if reasonably close
                return content[:pos + len(sep)] + "\n... (truncated)"

        # Fallback: hard truncate at word boundary
        pos = content.rfind(" ", 0, truncate_at)
        if pos > truncate_at // 2:
            return content[:pos] + " ... (truncated)"

        return content[:truncate_at] + "... (truncated)"
