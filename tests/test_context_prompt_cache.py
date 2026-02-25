"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

import asyncio
from datetime import datetime as real_datetime
from pathlib import Path
import datetime as datetime_module
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session


class _FakeDatetime(real_datetime):
    current = real_datetime(2026, 2, 24, 13, 59)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return cls.current


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_system_prompt_stays_stable_when_clock_changes(tmp_path, monkeypatch) -> None:
    """System prompt should not change just because wall clock minute changes."""
    monkeypatch.setattr(datetime_module, "datetime", _FakeDatetime)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    _FakeDatetime.current = real_datetime(2026, 2, 24, 13, 59)
    prompt1 = builder.build_system_prompt()

    _FakeDatetime.current = real_datetime(2026, 2, 24, 14, 0)
    prompt2 = builder.build_system_prompt()

    assert prompt1 == prompt2


def test_runtime_context_is_separate_untrusted_user_message(tmp_path) -> None:
    """Runtime metadata should be a separate user message before the actual user message."""
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    messages = builder.build_messages(
        history=[],
        current_message="Return exactly: OK",
        channel="cli",
        chat_id="direct",
    )

    assert messages[0]["role"] == "system"
    assert "## Current Session" not in messages[0]["content"]

    assert messages[-2]["role"] == "user"
    runtime_content = messages[-2]["content"]
    assert isinstance(runtime_content, str)
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in runtime_content
    assert "Current Time:" in runtime_content
    assert "Channel: cli" in runtime_content
    assert "Chat ID: direct" in runtime_content

    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "Return exactly: OK"


class _DummyBus:
    async def publish_outbound(self, _message):
        return None


def _make_loop(tmp_path: Path, memory_window: int = 100) -> tuple[AgentLoop, MagicMock]:
    workspace = _make_workspace(tmp_path)

    provider = MagicMock()
    provider.get_default_model.return_value = "anthropic/claude-sonnet-4-5"
    provider.chat = AsyncMock(return_value=LLMResponse(content="updated summary", tool_calls=[]))

    loop = AgentLoop(
        bus=_DummyBus(),
        provider=provider,
        workspace=workspace,
        memory_window=memory_window,
    )
    return loop, provider


def _make_session(message_count: int) -> Session:
    session = Session(key="cli:direct")
    for i in range(message_count):
        role = "user" if i % 2 == 0 else "assistant"
        session.add_message(role, f"{role}-{i}")
    return session


def test_system_prompt_can_include_stable_summary_block(tmp_path: Path) -> None:
    builder = ContextBuilder(_make_workspace(tmp_path))

    prompt = builder.build_system_prompt(session_summary="Older context summary")

    assert "# Session Summary (Compressed Context)" in prompt
    assert "Older context summary" in prompt


def test_rollover_compacts_old_prefix_in_batches(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, memory_window=100)
    session = _make_session(150)

    asyncio.run(loop._maybe_rollover_prompt_history(session))

    assert session.metadata["prompt_rollover_base_index"] == 50
    assert session.metadata["prompt_rollover_summary"] == "updated summary"
    provider.chat.assert_awaited_once()

    summary, history = loop._build_prompt_history(session)
    assert summary == "updated summary"
    assert len(history) == 100
    assert history[0]["content"] == "user-50"


def test_rollover_does_not_slide_every_turn_before_hard_limit(tmp_path: Path) -> None:
    loop, provider = _make_loop(tmp_path, memory_window=100)
    session = _make_session(150)

    asyncio.run(loop._maybe_rollover_prompt_history(session))
    provider.chat.reset_mock()

    # Add 10 messages (5 turns): still below hard limit after the first rollover.
    for i in range(150, 160):
        role = "user" if i % 2 == 0 else "assistant"
        session.add_message(role, f"{role}-{i}")

    asyncio.run(loop._maybe_rollover_prompt_history(session))

    # Base index should stay fixed, avoiding per-turn sliding-window churn.
    assert session.metadata["prompt_rollover_base_index"] == 50
    provider.chat.assert_not_awaited()

    _, history = loop._build_prompt_history(session)
    assert history[0]["content"] == "user-50"
    assert len(history) == 110
