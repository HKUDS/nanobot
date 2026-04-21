"""Tests for /status command with context breakdown integration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_status
from nanobot.command.router import CommandContext

from tests.conftest import (
    _FakeContextBuilder,
    _FakeMemory,
    _FakeSession,
    _FakeSkills,
    _FakeTools,
)


class _FakeConsolidator:
    """Mock Consolidator for testing."""

    def estimate_session_prompt_tokens(self, session: Any) -> tuple[int, str]:
        return (5000, "tiktoken")


class _FakeSubagents:
    """Mock SubagentManager for testing."""

    def get_running_count_by_session(self, session_key: str) -> int:
        return 0


def _make_ctx(
    *,
    session_messages: list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    last_usage: dict[str, int] | None = None,
    memory_content: str = "",
    skills_summary: str = "Available Skills: skill1, skill2",
) -> CommandContext:
    """Create a CommandContext for testing /status."""
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/status")

    session = _FakeSession(messages=session_messages or [])

    context_builder = _FakeContextBuilder(
        identity="Identity: workspace=/test, platform=macOS",
        bootstrap="Bootstrap: AGENTS.md, SOUL.md",
        memory=_FakeMemory(memory_content=memory_content),
        skills=_FakeSkills(skills_summary=skills_summary),
    )

    loop = SimpleNamespace(
        context=context_builder,
        tools=_FakeTools(tools=tools or []),
        consolidator=_FakeConsolidator(),
        subagents=_FakeSubagents(),
        _last_usage=last_usage or {},
        _start_time=1000000.0,
        model="test-model",
        context_window_tokens=128000,
        sessions=SimpleNamespace(get_or_create=lambda k: session),
        _active_tasks={},
        provider=SimpleNamespace(generation=SimpleNamespace(max_tokens=8192)),
    )

    return CommandContext(
        msg=msg,
        session=session,
        key=msg.session_key,
        raw="/status",
        args="",
        loop=loop,
    )


@pytest.mark.asyncio
async def test_status_includes_basic_info():
    """Test that /status shows basic runtime info."""
    ctx = _make_ctx(
        last_usage={"prompt_tokens": 1000, "completion_tokens": 100, "cached_tokens": 500},
    )

    out = await cmd_status(ctx)

    # Basic status info should be present
    assert "nanobot" in out.content.lower()
    assert "test-model" in out.content.lower()
    assert "1000 in / 100 out" in out.content


@pytest.mark.asyncio
async def test_status_includes_context_breakdown():
    """Test that /status includes context breakdown section."""
    ctx = _make_ctx(
        session_messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        tools=[{"name": "tool1", "description": "Test tool"}],
        last_usage={"prompt_tokens": 2000, "completion_tokens": 200, "cached_tokens": 1000},
    )

    out = await cmd_status(ctx)

    # Context breakdown should be present
    assert "Context Breakdown" in out.content
    assert "System Prompt:" in out.content
    assert "Conversation:" in out.content
    assert "Tools Definitions:" in out.content


@pytest.mark.asyncio
async def test_status_shows_tool_names():
    """Test that tool names are displayed."""
    ctx = _make_ctx(
        tools=[
            {"name": "read_file", "description": "Read files"},
            {"name": "write_file", "description": "Write files"},
            {"name": "exec", "description": "Execute commands"},
        ],
    )

    out = await cmd_status(ctx)

    assert "read_file" in out.content
    assert "write_file" in out.content
    assert "exec" in out.content


@pytest.mark.asyncio
async def test_status_without_breakdown_still_works():
    """Test that /status works even if breakdown calculation fails."""
    # Create a broken context that will fail breakdown calculation
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/status")
    session = _FakeSession()

    # Broken context builder
    broken_context = SimpleNamespace()

    loop = SimpleNamespace(
        context=broken_context,
        tools=_FakeTools(),
        consolidator=_FakeConsolidator(),
        subagents=_FakeSubagents(),
        _last_usage={"prompt_tokens": 1000, "completion_tokens": 100},
        _start_time=1000000.0,
        model="test-model",
        context_window_tokens=128000,
        sessions=SimpleNamespace(get_or_create=lambda k: session),
        _active_tasks={},
        provider=SimpleNamespace(generation=SimpleNamespace(max_tokens=8192)),
    )

    ctx = CommandContext(
        msg=msg,
        session=session,
        key=msg.session_key,
        raw="/status",
        args="",
        loop=loop,
    )

    out = await cmd_status(ctx)

    # Should still return basic status even if breakdown fails
    assert "nanobot" in out.content.lower()
    assert "test-model" in out.content.lower()
    # Breakdown section should be missing
    assert "Context Breakdown" not in out.content
