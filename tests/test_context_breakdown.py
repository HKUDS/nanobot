"""Tests for context breakdown calculation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.utils.helpers import build_status_content, calculate_context_breakdown


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

    def build_skills_summary(self) -> str:
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

    def _get_identity(self, channel: str | None = None) -> str:
        return self._identity

    def _load_bootstrap_files(self) -> str:
        return self._bootstrap

    @staticmethod
    def _build_runtime_context(
        channel: str | None,
        chat_id: str | None,
        timezone: str | None = None,
        session_summary: str | None = None,
    ) -> str:
        return "[Runtime Context]\nCurrent Time: 2026-04-17\n[/Runtime Context]"


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


class _FakeLoop:
    """Mock AgentLoop for testing."""

    def __init__(self, tools: _FakeTools | None = None):
        self.tools = tools or _FakeTools()


def test_calculate_context_breakdown_basic():
    """Test basic context breakdown calculation."""
    context_builder = _FakeContextBuilder(
        identity="Identity: 100 chars",
        bootstrap="Bootstrap: 200 chars",
        memory=_FakeMemory(memory_content="Memory: 300 chars"),
        skills=_FakeSkills(
            always_skills=["skill1"],
            always_content="Always Skills: 150 chars",
            skills_summary="Skills Summary: 250 chars",
        ),
    )

    session = _FakeSession(
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
    )

    loop = _FakeLoop(
        tools=_FakeTools(
            tools=[
                {"name": "tool1", "description": "A test tool"},
                {"name": "tool2", "description": "Another tool"},
            ]
        )
    )

    breakdown = calculate_context_breakdown(context_builder, session, loop)

    # Verify structure
    assert "parts" in breakdown
    assert "total_chars" in breakdown
    assert "history_stats" in breakdown
    assert "tools_stats" in breakdown
    assert "tool_names" in breakdown

    # Verify parts exist
    parts = breakdown["parts"]
    assert "identity" in parts
    assert "bootstrap" in parts
    assert "memory" in parts
    assert "always_skills" in parts
    assert "skills_summary" in parts
    assert "recent_history" in parts
    assert "system_prompt_total" in parts
    assert "history_messages" in parts
    assert "tools_definitions" in parts
    assert "runtime_context" in parts

    # Verify tool names
    assert "tool1" in breakdown["tool_names"]
    assert "tool2" in breakdown["tool_names"]


def test_build_status_content_with_breakdown():
    """Test that build_status_content correctly formats breakdown."""
    breakdown = {
        "parts": {
            "identity": 500,
            "bootstrap": 3200,
            "memory": 4500,
            "always_skills": 2000,
            "skills_summary": 4500,
            "recent_history": 500,
            "system_prompt_total": 15200,
            "history_messages": 18300,
            "tools_definitions": 5800,
            "runtime_context": 300,
        },
        "total_chars": 39600,
        "history_stats": {
            "total_messages": 42,
            "user_messages": 25,
            "assistant_messages": 17,
        },
        "tools_stats": {
            "total_tools": 12,
        },
        "tool_names": ["read_file", "write_file", "exec"],
    }

    last_usage = {
        "prompt_tokens": 45231,
        "completion_tokens": 1234,
        "cached_tokens": 35280,
    }

    output = build_status_content(
        version="0.1.0",
        model="test-model",
        start_time=1000000.0,
        last_usage=last_usage,
        context_window_tokens=128000,
        session_msg_count=42,
        context_tokens_estimate=50000,
        context_breakdown=breakdown,
    )

    # Verify basic status info
    assert "nanobot" in output
    assert "test-model" in output

    # Verify context breakdown is present
    assert "Context Breakdown" in output
    assert "System Prompt:" in output
    assert "History Messages:" in output
    assert "Tools Definitions:" in output

    # Verify tool names are shown
    assert "read_file" in output
    assert "write_file" in output
    assert "exec" in output

    # Verify token usage
    assert "45,231" in output
    assert "1,234" in output


def test_build_status_content_without_breakdown():
    """Test that build_status_content works without breakdown."""
    output = build_status_content(
        version="0.1.0",
        model="test-model",
        start_time=1000000.0,
        last_usage={"prompt_tokens": 1000, "completion_tokens": 100},
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=5000,
    )

    # Should work without breakdown
    assert "nanobot" in output
    assert "test-model" in output
    # Should NOT have breakdown section
    assert "Context Breakdown" not in output
