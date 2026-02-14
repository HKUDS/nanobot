"""Memory system for persistent agent memory."""

from pathlib import Path

from nanobot.utils.helpers import ensure_dir


def today_date() -> str:
    """Get today's date in YYYY-MM-DD format."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d")


class MemoryStore:
    """Memory system: MEMORY.md (long-term facts) + daily notes (YYYY-MM-DD.md)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = workspace / "MEMORY.md"  # Moved to workspace root
        self.history_file = self.memory_dir / "HISTORY.md"

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
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        """
        Get memory context for the agent.

        Returns:
            Formatted memory context including MEMORY.md.
            Note: Daily notes (YYYY-MM-DD.md) are in memory/ folder and NOT loaded here.
            Use read_file to access daily notes when needed.
        """
        parts = []

        # Long-term memory (MEMORY.md in workspace root)
        long_term = self.read_long_term()
        if long_term:
            parts.append("## Long-term Memory\n" + long_term)

        # Note: Daily notes (YYYY-MM-DD.md) are in memory/ folder
        # They are NOT automatically loaded to save context space.
        # Use read_file(path="memory/YYYY-MM-DD.md") when you need to review them.

        return "\n\n".join(parts) if parts else ""
