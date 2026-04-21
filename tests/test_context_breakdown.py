"""Tests for context breakdown calculation."""

from __future__ import annotations

from tests.conftest import (
    _FakeContextBuilder,
    _FakeMemory,
    _FakeSession,
    _FakeSkills,
    _FakeTools,
)

from nanobot.utils.helpers import build_status_content, calculate_context_breakdown


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
    assert "tokens" in breakdown
    assert "total_tokens" in breakdown
    assert "history_stats" in breakdown
    assert "tools_stats" in breakdown
    assert "tool_names" in breakdown

    # Verify tokens exist
    tokens = breakdown["tokens"]
    assert "identity" in tokens
    assert "bootstrap" in tokens
    assert "memory" in tokens
    assert "always_skills" in tokens
    assert "skills_summary" in tokens
    assert "recent_history" in tokens
    assert "system_prompt_total" in tokens
    assert "history_messages" in tokens
    assert "tools_definitions" in tokens
    assert "runtime_context" in tokens

    # Verify tool names
    assert "tool1" in breakdown["tool_names"]
    assert "tool2" in breakdown["tool_names"]


def test_build_status_content_with_breakdown():
    """Test that build_status_content correctly formats breakdown."""
    breakdown = {
        "tokens": {
            "identity": 125,
            "bootstrap": 800,
            "memory": 1125,
            "always_skills": 500,
            "skills_summary": 1125,
            "recent_history": 125,
            "system_prompt_total": 3800,
            "history_messages": 4575,
            "tools_definitions": 1450,
            "runtime_context": 75,
        },
        "total_tokens": 9900,
        "history_stats": {
            "total_messages": 42,
            "user_messages": 25,
            "assistant_messages": 17,
            "tool_messages": 0,
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
    assert "System Prompt" in output
    assert "Conversation" in output
    assert "Tools" in output

    # Verify tool names are shown
    assert "read_file" in output
    assert "write_file" in output
    assert "exec" in output

    # Verify token usage (header line uses raw numbers)
    assert "45231" in output
    assert "1234" in output

    # Verify tool messages count shown when > 0
    assert "25U / 17A" in output


def test_build_status_content_with_tool_messages():
    """Test that tool message count is shown when present."""
    breakdown = {
        "tokens": {
            "identity": 100,
            "bootstrap": 200,
            "memory": 300,
            "always_skills": 0,
            "skills_summary": 150,
            "recent_history": 0,
            "system_prompt_total": 750,
            "history_messages": 2000,
            "tools_definitions": 500,
            "runtime_context": 50,
        },
        "total_tokens": 3300,
        "history_stats": {
            "total_messages": 10,
            "user_messages": 3,
            "assistant_messages": 3,
            "tool_messages": 4,
        },
        "tools_stats": {"total_tools": 5},
        "tool_names": [],
    }

    output = build_status_content(
        version="0.1.0",
        model="test-model",
        start_time=1000000.0,
        last_usage={"prompt_tokens": 1000, "completion_tokens": 100},
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=3000,
        context_breakdown=breakdown,
    )

    assert "3U / 3A / 4T" in output


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
