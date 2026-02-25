"""Memory system for persistent agent memory."""

from pathlib import Path

from nanobot.utils.helpers import ensure_dir


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

    def __init__(self, workspace: Path, profile: str | None = None):
        self.workspace = workspace
        self.profile = profile
        self.memory_dir = ensure_dir(workspace / "memory")

        # Set up profile-specific memory paths
        if profile:
            self.profile_memory_dir = ensure_dir(self.memory_dir / "profiles" / profile)
            self.memory_file = self.profile_memory_dir / "MEMORY.md"
            self.history_file = self.profile_memory_dir / "HISTORY.md"
        else:
            self.profile_memory_dir = None
            self.memory_file = self.memory_dir / "MEMORY.md"
            self.history_file = self.memory_dir / "HISTORY.md"

    def _get_global_memory_file(self) -> Path:
        """Get the global memory file path."""
        return self.memory_dir / "MEMORY.md"

    def _get_global_history_file(self) -> Path:
        """Get the global history file path."""
        return self.memory_dir / "HISTORY.md"

    def read_long_term(self, include_global: bool = True) -> str:
        """Read long-term memory. For profile-specific stores, also include global if requested."""
        parts = []

        # Read profile memory first (if applicable)
        if self.profile and self.memory_file.exists():
            content = self.memory_file.read_text(encoding="utf-8")
            if content:
                parts.append(f"## Profile Memory ({self.profile})\n{content}")

        # Read global memory
        if include_global:
            global_file = self._get_global_memory_file()
            if global_file.exists():
                content = global_file.read_text(encoding="utf-8")
                if content:
                    parts.append(f"## Global Memory\n{content}")

        return "\n\n".join(parts) if parts else ""

    def write_long_term(self, content: str) -> None:
        """Write to the appropriate memory file."""
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        """Append to the appropriate history file."""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(
        self,
        isolation: str = "shared",
        include_global: bool = True,
    ) -> str:
        """
        Get memory context based on isolation mode.

        Args:
            isolation: Memory isolation mode ("shared", "isolated", "hierarchical")
            include_global: Whether to include global memory (only for hierarchical mode)

        Returns:
            Formatted memory context string.
        """
        if isolation == "isolated" or self.profile is None:
            # Isolated: only profile memory, or global if no profile
            long_term = self.read_long_term(include_global=False)
            return f"## Long-term Memory\n{long_term}" if long_term else ""

        elif isolation == "hierarchical":
            # Hierarchical: profile memory + global memory
            long_term = self.read_long_term(include_global=include_global)
            if long_term:
                return f"## Long-term Memory\n{long_term}"
            return ""

        else:  # shared
            # Shared: always use global memory
            global_file = self._get_global_memory_file()
            if global_file.exists():
                content = global_file.read_text(encoding="utf-8")
                return f"## Long-term Memory\n{content}" if content else ""
            return ""

    def read_global_memory(self) -> str:
        """Read only the global memory file."""
        global_file = self._get_global_memory_file()
        if global_file.exists():
            return global_file.read_text(encoding="utf-8")
        return ""

    def write_global_memory(self, content: str) -> None:
        """Write to the global memory file."""
        global_file = self._get_global_memory_file()
        global_file.parent.mkdir(parents=True, exist_ok=True)
        global_file.write_text(content, encoding="utf-8")

    def get_relevant_context(
        self,
        task: str,
        max_chars: int = 2000,
    ) -> str:
        """
        Get relevant memory context for a specific task.
        Searches global and profile-specific history for relevant entries.

        Uses improved relevance scoring based on multi-word phrase matching
        to avoid returning unrelated content.

        Args:
            task: The task description to match against.
            max_chars: Maximum characters to return.

        Returns:
            Relevant memory entries concatenated together.
        """
        import re
        from math import log

        # Extract key phrases (2-3 word sequences) and single words
        # This helps match "weather thanh hoa" as a phrase rather than just "thanh"
        task_lower = task.lower()

        # Extract meaningful phrases (2-3 word sequences)
        words = re.findall(r"\b\w{3,}\b", task_lower)
        if len(words) < 2:
            return ""

        # Build phrase pairs (bigrams) and triplets (trigrams)
        phrases = set()
        for i in range(len(words) - 1):
            phrases.add(words[i] + " " + words[i + 1])  # bigrams
        for i in range(len(words) - 2):
            phrases.add(words[i] + " " + words[i + 1] + " " + words[i + 2])  # trigrams

        # Also include individual words for fallback
        individual_words = set(w for w in words if len(w) >= 3)

        # Score each entry by phrase and word matches
        def score_entry(entry: str) -> float:
            entry_lower = entry.lower()
            score = 0.0

            # Phrase matches get higher scores (prefer multi-word matches)
            for phrase in phrases:
                if phrase in entry_lower:
                    score += 10.0 * len(phrase.split())  # Longer phrases score higher

            # Word matches (lower score, used for tie-breaking)
            for word in individual_words:
                if word in entry_lower:
                    score += 1.0

            return score

        def extract_entries(content: str) -> list[str]:
            """Extract individual entries from history file."""
            # History entries are separated by double newlines
            entries = re.split(r'\n\n+', content.strip())
            return [e.strip() for e in entries if e.strip() and len(e.strip()) > 20]

        # Search and score profile history if applicable
        profile_results = []
        if self.profile and self.history_file.exists():
            content = self.history_file.read_text(encoding="utf-8")
            entries = extract_entries(content)
            for entry in entries:
                score = score_entry(entry)
                if score >= 3.0:  # Minimum threshold: at least one phrase or 3 words
                    profile_results.append((score, entry))

        # Search and score global history
        global_results = []
        global_history = self._get_global_history_file()
        if global_history.exists():
            content = global_history.read_text(encoding="utf-8")
            entries = extract_entries(content)
            for entry in entries:
                score = score_entry(entry)
                if score >= 3.0:
                    global_results.append((score, entry))

        # Sort by score (highest first) and take top results
        profile_results.sort(key=lambda x: x[0], reverse=True)
        global_results.sort(key=lambda x: x[0], reverse=True)

        # Build output from top matches
        results = []
        combined_length = 0

        # Add top profile results (up to 3)
        for score, entry in profile_results[:3]:
            if combined_length + len(entry) > max_chars:
                break
            results.append(entry)
            combined_length += len(entry)

        # Add top global results (up to 3)
        for score, entry in global_results[:3]:
            if combined_length + len(entry) > max_chars:
                break
            results.append(entry)
            combined_length += len(entry)

        if not results:
            return ""

        return "\n\n".join(results)
