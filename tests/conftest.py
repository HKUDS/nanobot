"""Shared mock classes for context breakdown tests."""

from __future__ import annotations

from typing import Any


class _FakeMemory:
    """Mock MemoryStore for testing."""

    def __init__(
        self,
        memory_content: str = "",
        history_entries: list[dict[str, Any]] | None = None,
        last_dream_cursor: int = 0,
    ):
        self._memory_content = memory_content
        self._history_entries = history_entries or []
        self._last_dream_cursor = last_dream_cursor

    def get_memory_context(self) -> str:
        return self._memory_content

    def read_unprocessed_history(self, since_cursor: int = 0) -> list[dict[str, Any]]:
        return self._history_entries

    def get_last_dream_cursor(self) -> int:
        return self._last_dream_cursor


class _FakeSkills:
    """Mock SkillsLoader for testing."""

    def __init__(
        self,
        always_skills: list[str] | None = None,
        always_content: str = "",
        skills_summary: str = "",
    ):
        self._always_skills = always_skills or []
        self._always_content = always_content
        self._skills_summary = skills_summary

    def get_always_skills(self) -> list[str]:
        return self._always_skills

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        return self._always_content

    def build_skills_summary(self, exclude: set[str] | None = None) -> str:
        return self._skills_summary


class _FakeContextBuilder:
    """Mock ContextBuilder for testing."""

    _MAX_RECENT_HISTORY = 50

    def __init__(
        self,
        identity: str = "Test Identity",
        bootstrap: str = "Bootstrap Files",
        memory: _FakeMemory | None = None,
        skills: _FakeSkills | None = None,
        timezone: str | None = None,
    ):
        self._identity = identity
        self._bootstrap = bootstrap
        self.memory = memory or _FakeMemory()
        self.skills = skills or _FakeSkills()
        self.timezone = timezone

    def get_context_parts(self, channel: str | None = None, chat_id: str | None = None) -> dict[str, str]:
        """Public API matching real ContextBuilder."""
        return {
            "identity": self._identity,
            "bootstrap": self._bootstrap,
            "memory": self.memory.get_memory_context() or "",
            "always_skills": "",
            "skills_summary": self.skills.build_skills_summary() or "",
            "recent_history": "",
            "runtime_context": "[Runtime Context]\nCurrent Time: 2026-04-17\n[/Runtime Context]",
        }

    def build_system_prompt(self, skill_names: list[str] | None = None, channel: str | None = None) -> str:
        """Mimic real ContextBuilder: join non-empty parts with separators."""
        parts = [self._identity]
        if self._bootstrap:
            parts.append(self._bootstrap)
        memory_ctx = self.memory.get_memory_context()
        if memory_ctx:
            parts.append(f"# Memory\n\n{memory_ctx}")
        return "\n\n---\n\n".join(parts)


class _FakeSession:
    """Mock Session for testing."""

    def __init__(self, messages: list[dict[str, Any]] | None = None):
        self.messages = messages or []

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        return self.messages if max_messages == 0 else self.messages[-max_messages:]


class _FakeTools:
    """Mock ToolRegistry for testing."""

    def __init__(self, tools: list[dict[str, Any]] | None = None):
        self._tools = tools or []

    def get_definitions(self) -> list[dict[str, Any]]:
        return self._tools
