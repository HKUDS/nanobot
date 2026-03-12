"""Load and cache prompt templates from ``nanobot/templates/prompts/``.

Prompts are stored as plain text ``.md`` files.  The loader reads each
file once and caches the content for the lifetime of the process.

Users can override any built-in prompt by placing a file with the same
name in their workspace's ``prompts/`` directory (relative to the
workspace root).

Usage::

    from nanobot.agent.prompt_loader import prompts

    plan_text = prompts.get("plan")
    critique  = prompts.get("critique")
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

# Built-in prompts ship inside the package
_BUILTIN_DIR = Path(__file__).resolve().parent.parent / "templates" / "prompts"


class PromptLoader:
    """Read-through cache for prompt template files."""

    def __init__(self, *, workspace: Path | None = None) -> None:
        self._cache: dict[str, str] = {}
        self._workspace = workspace

    def get(self, name: str) -> str:
        """Return the prompt text for *name* (without ``.md`` extension).

        Resolution order:
        1. ``<workspace>/prompts/<name>.md``  (user override)
        2. ``nanobot/templates/prompts/<name>.md``  (built-in)
        """
        if name in self._cache:
            return self._cache[name]

        text = self._load(name)
        self._cache[name] = text
        return text

    def _load(self, name: str) -> str:
        # User override
        if self._workspace:
            override = self._workspace / "prompts" / f"{name}.md"
            if override.is_file():
                text = override.read_text(encoding="utf-8").strip()
                logger.debug("Loaded prompt override: {}", override)
                return text

        # Built-in
        builtin = _BUILTIN_DIR / f"{name}.md"
        if builtin.is_file():
            return builtin.read_text(encoding="utf-8").strip()

        logger.warning("Prompt template '{}' not found", name)
        return ""

    def preload(self) -> None:
        """Eagerly load all built-in prompts into cache."""
        if _BUILTIN_DIR.is_dir():
            for p in _BUILTIN_DIR.glob("*.md"):
                self.get(p.stem)

    def clear(self) -> None:
        """Drop cached prompts (useful for testing)."""
        self._cache.clear()


# Module-level singleton (workspace set later by AgentLoop.__init__)
prompts = PromptLoader()
