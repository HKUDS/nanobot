"""Shared types for version control backends (GitStore, SQLiteStore)."""

from dataclasses import dataclass


@dataclass
class CommitInfo:
    """Information about a single commit in the version history."""

    sha: str  # Short SHA (8 chars) or random 8-char ID
    message: str
    timestamp: str  # Formatted datetime

    def format(self, diff: str = "") -> str:
        """Format this commit for display, optionally with a diff."""
        header = f"## {self.message.splitlines()[0]}\n`{self.sha}` — {self.timestamp}\n"
        if diff:
            return f"{header}\n```diff\n{diff}\n```"
        return f"{header}\n(no file changes)"
