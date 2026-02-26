"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

from datetime import datetime as real_datetime
from pathlib import Path
import datetime as datetime_module
from unittest.mock import MagicMock

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
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


def _make_loop(tmp_path: Path, memory_window: int = 100) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "anthropic/claude-sonnet-4-5"
    return AgentLoop(
        bus=_DummyBus(),
        provider=provider,
        workspace=_make_workspace(tmp_path),
        memory_window=memory_window,
    )


def _make_session(message_count: int) -> Session:
    session = Session(key="cli:direct")
    for i in range(message_count):
        role = "user" if i % 2 == 0 else "assistant"
        session.add_message(role, f"{role}-{i}")
    return session


def test_rollover_batches_old_prefix_without_summary(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, memory_window=100)
    session = _make_session(150)

    loop._maybe_rollover_prompt_history(session)

    assert session.metadata["prompt_rollover_base_index"] == 100

    history = loop._build_prompt_history(session)
    assert len(history) == 50
    assert history[0]["content"] == "user-100"


def test_rollover_does_not_slide_every_turn_before_hard_limit(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, memory_window=100)
    session = _make_session(150)

    loop._maybe_rollover_prompt_history(session)

    for i in range(150, 160):
        role = "user" if i % 2 == 0 else "assistant"
        session.add_message(role, f"{role}-{i}")

    loop._maybe_rollover_prompt_history(session)

    assert session.metadata["prompt_rollover_base_index"] == 100

    history = loop._build_prompt_history(session)
    assert history[0]["content"] == "user-100"
    assert len(history) == 60
