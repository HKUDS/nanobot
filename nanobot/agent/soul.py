"""Soul loader - loads personality and context files for the agent.

This module provides functionality to load .md files that define the agent's
personality, memory, and behavior rules. Similar to OpenClaw's workspace files.

Files loaded (in order):
- SOUL.md: Core personality, tone, fundamental rules
- IDENTITY.md: Who the agent is (name, avatar, vibe)
- USER.md: About the user (preferences, context)
- MEMORY.md: Long-term curated memories
- AGENTS.md: Behavior rules and constraints
- TOOLS.md: Tool-specific notes and preferences
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import SoulConfig


class SoulLoader:
    """Loads and manages soul/personality files for the agent."""

    def __init__(self, config: SoulConfig):
        """Initialize the soul loader.

        Args:
            config: Soul configuration with path and file list.
        """
        self.config = config
        self.path = Path(config.path).expanduser()
        self._cached_content: str | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0  # Re-read files every 60 seconds

    def _should_refresh_cache(self) -> bool:
        """Check if cache should be refreshed."""
        import time
        return (
            self._cached_content is None or
            (time.time() - self._cache_time) > self._cache_ttl
        )

    def load(
        self,
        channel: str | None = None,
        model: str | None = None,
        session_key: str | None = None,
    ) -> str:
        """Load all soul files and return combined system prompt.

        Args:
            channel: Current channel (whatsapp, telegram, etc.)
            model: Current model being used
            session_key: Current session identifier

        Returns:
            Combined system prompt with all soul content.
        """
        if not self.config.enabled:
            return ""

        # Check cache
        if not self._should_refresh_cache():
            # Still need to update runtime info
            return self._inject_runtime(
                self._cached_content or "",
                channel=channel,
                model=model,
                session_key=session_key,
            )

        sections: list[str] = []

        # Load each file
        for filename in self.config.files:
            filepath = self.path / filename
            if filepath.exists():
                try:
                    content = filepath.read_text(encoding="utf-8").strip()
                    if content:
                        sections.append(f"## {filename}\n{content}")
                        logger.debug(f"Loaded soul file: {filename} ({len(content)} chars)")
                except Exception as e:
                    logger.warning(f"Failed to load soul file {filename}: {e}")
            else:
                logger.debug(f"Soul file not found (skipping): {filepath}")

        if not sections:
            logger.warning(f"No soul files found in {self.path}")
            self._cached_content = ""
        else:
            self._cached_content = "\n\n".join(sections)
            logger.info(f"Loaded {len(sections)} soul files ({len(self._cached_content)} chars total)")

        import time
        self._cache_time = time.time()

        return self._inject_runtime(
            self._cached_content,
            channel=channel,
            model=model,
            session_key=session_key,
        )

    def _inject_runtime(
        self,
        content: str,
        channel: str | None = None,
        model: str | None = None,
        session_key: str | None = None,
    ) -> str:
        """Inject runtime information into the soul content.

        Args:
            content: Base soul content
            channel: Current channel
            model: Current model
            session_key: Current session

        Returns:
            Content with runtime info appended.
        """
        parts = [content] if content else []

        # Inject datetime
        if self.config.inject_datetime:
            now = datetime.now(timezone.utc)
            # Also try to get local timezone
            local_tz = os.environ.get("TZ", "UTC")
            datetime_section = f"""## Current Date & Time
UTC: {now.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")}
Timezone: {local_tz}"""
            parts.append(datetime_section)

        # Inject runtime info
        if self.config.inject_runtime and (channel or model or session_key):
            runtime_parts = ["## Runtime"]
            if model:
                runtime_parts.append(f"Model: {model}")
            if channel:
                runtime_parts.append(f"Channel: {channel}")
            if session_key:
                runtime_parts.append(f"Session: {session_key}")
            parts.append("\n".join(runtime_parts))

        return "\n\n".join(parts)

    def get_file(self, filename: str) -> str | None:
        """Get content of a specific soul file.

        Args:
            filename: Name of the file (e.g., "MEMORY.md")

        Returns:
            File content or None if not found.
        """
        filepath = self.path / filename
        if filepath.exists():
            try:
                return filepath.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to read {filename}: {e}")
        return None

    def update_file(self, filename: str, content: str) -> bool:
        """Update a soul file.

        Args:
            filename: Name of the file to update
            content: New content

        Returns:
            True if successful.
        """
        # Only allow updating known files
        if filename not in self.config.files:
            logger.warning(f"Cannot update unknown soul file: {filename}")
            return False

        filepath = self.path / filename
        try:
            # Ensure directory exists
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
            logger.info(f"Updated soul file: {filename}")
            # Invalidate cache
            self._cached_content = None
            return True
        except Exception as e:
            logger.error(f"Failed to update {filename}: {e}")
            return False

    def append_to_memory(self, entry: str) -> bool:
        """Append an entry to MEMORY.md.

        Args:
            entry: Memory entry to append

        Returns:
            True if successful.
        """
        memory_file = self.path / "MEMORY.md"
        try:
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Read existing content
            existing = ""
            if memory_file.exists():
                existing = memory_file.read_text(encoding="utf-8")

            # Append new entry with timestamp
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            new_entry = f"\n\n## [{timestamp}]\n{entry}"
            
            memory_file.write_text(existing + new_entry, encoding="utf-8")
            logger.info(f"Appended to MEMORY.md: {entry[:50]}...")
            
            # Invalidate cache
            self._cached_content = None
            return True
        except Exception as e:
            logger.error(f"Failed to append to MEMORY.md: {e}")
            return False


def create_soul_loader(config: SoulConfig) -> SoulLoader:
    """Create a soul loader instance.

    Args:
        config: Soul configuration

    Returns:
        Configured SoulLoader instance.
    """
    return SoulLoader(config)
