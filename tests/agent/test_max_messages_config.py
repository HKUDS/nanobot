"""Tests for max_messages config wiring into session history replay."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session

DEFAULT_MAX_MESSAGES = 120


def _make_loop(
    tmp_path: Path,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    *,
    microcompact_tool_results: bool = True,
) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        max_messages=max_messages,
        microcompact_tool_results=microcompact_tool_results,
    )


def _populated_session(n: int) -> Session:
    """Create a session with *n* user/assistant turn pairs."""
    session = Session(key="test:populated")
    for i in range(n):
        session.add_message("user", f"msg-{i}")
        session.add_message("assistant", f"reply-{i}")
    return session


def _tool_round(call_id: str) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "name": "x", "content": "ok"},
    ]


class TestMaxMessagesInit:
    """Verify AgentLoop stores the config value correctly."""

    def test_default_is_builtin_limit(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._max_messages == DEFAULT_MAX_MESSAGES

    def test_positive_value_stored(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, max_messages=25)
        assert loop._max_messages == 25

    def test_zero_uses_builtin_limit(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, max_messages=0)
        assert loop._max_messages == DEFAULT_MAX_MESSAGES

    def test_negative_treated_as_builtin_limit(self, tmp_path: Path) -> None:
        """Negative values should not produce negative slicing."""
        loop = _make_loop(tmp_path, max_messages=-5)
        assert loop._max_messages == DEFAULT_MAX_MESSAGES


class TestGetHistoryWithMaxMessages:
    """Verify get_history respects max_messages parameter."""

    def test_default_uses_builtin_limit(self) -> None:
        session = _populated_session(80)
        history = session.get_history()
        assert len(history) <= DEFAULT_MAX_MESSAGES

    def test_explicit_max_messages_limits_output(self) -> None:
        session = _populated_session(40)  # 80 messages total
        history = session.get_history(max_messages=20)
        assert len(history) <= 20

    def test_max_messages_starts_at_user_turn(self) -> None:
        """Sliced history should start with a user message, not mid-turn."""
        session = _populated_session(30)  # 60 messages
        history = session.get_history(max_messages=25)
        assert history[0]["role"] == "user"

    def test_max_messages_zero_uses_builtin_limit(self) -> None:
        session = _populated_session(80)  # 160 messages total
        history = session.get_history(max_messages=0)
        assert len(history) <= DEFAULT_MAX_MESSAGES

    def test_small_session_unaffected(self) -> None:
        """When session has fewer messages than max_messages, all are returned."""
        session = _populated_session(5)  # 10 messages
        history = session.get_history(max_messages=25)
        assert len(history) == 10


class TestMaxMessagesIntegration:
    """Verify the config flows from AgentLoop into get_history calls."""

    @pytest.mark.asyncio
    async def test_process_message_passes_config_to_history_call(self, tmp_path: Path) -> None:
        """The real message path should pass max_messages into session history replay."""
        loop = _make_loop(tmp_path, max_messages=25)
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[], usage={})
        )
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        session = loop.sessions.get_or_create("cli:test")
        with patch.object(session, "get_history", wraps=session.get_history) as mock_hist:
            result = await loop._process_message(
                InboundMessage(channel="cli", sender_id="user", chat_id="test", content="hello")
            )

        assert result is not None
        assert mock_hist.call_count == 1
        assert mock_hist.call_args.kwargs["max_messages"] == 25
        assert mock_hist.call_args.kwargs["extend_to_user"] is False

    @pytest.mark.asyncio
    async def test_zero_config_passes_builtin_limit_to_history_call(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, max_messages=0)
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[], usage={})
        )
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        session = loop.sessions.get_or_create("cli:test")
        with patch.object(session, "get_history", wraps=session.get_history) as mock_hist:
            result = await loop._process_message(
                InboundMessage(channel="cli", sender_id="user", chat_id="test", content="hello")
            )

        assert result is not None
        assert mock_hist.call_args.kwargs["max_messages"] == DEFAULT_MAX_MESSAGES
        assert mock_hist.call_args.kwargs["extend_to_user"] is False

    @pytest.mark.asyncio
    async def test_process_message_uses_current_user_as_replay_boundary(
        self,
        tmp_path: Path,
    ) -> None:
        """A live user turn should not extend history to an older long tool turn."""
        loop = _make_loop(tmp_path, max_messages=6)
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[], usage={})
        )
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        session = loop.sessions.get_or_create("cli:test")
        session.add_message("user", "old")
        session.add_message("assistant", "old answer")
        session.add_message("user", "long older turn")
        for i in range(8):
            session.messages.extend(_tool_round(f"older-{i}"))
        session.add_message("assistant", "older final")

        with patch.object(session, "get_history", wraps=session.get_history) as mock_hist:
            result = await loop._process_message(
                InboundMessage(
                    channel="cli",
                    sender_id="user",
                    chat_id="test",
                    content="new question",
                )
            )

        assert result is not None
        assert mock_hist.call_args.kwargs["extend_to_user"] is False
        sent_messages = loop.provider.chat_with_retry.await_args.kwargs["messages"]
        sent_text = "\n".join(str(message.get("content")) for message in sent_messages)
        assert "new question" in sent_text
        assert "long older turn" not in sent_text


class TestSchemaConfig:
    """Verify the config schema accepts max_messages."""

    def test_schema_default(self) -> None:
        from nanobot.config.schema import AgentDefaults

        defaults = AgentDefaults()
        assert defaults.max_messages == DEFAULT_MAX_MESSAGES

    def test_schema_accepts_zero_as_builtin_limit(self) -> None:
        from nanobot.config.schema import AgentDefaults

        defaults = AgentDefaults(max_messages=0)
        assert defaults.max_messages == 0

    def test_schema_accepts_positive(self) -> None:
        from nanobot.config.schema import AgentDefaults

        defaults = AgentDefaults(max_messages=25)
        assert defaults.max_messages == 25

    def test_schema_rejects_negative(self) -> None:
        from nanobot.config.schema import AgentDefaults

        with pytest.raises(Exception):  # Pydantic validation error
            AgentDefaults(max_messages=-1)


class TestMicrocompactToolResultsConfig:
    """Verify #4222 prompt-cache opt-out wiring."""

    def test_schema_default_enabled(self) -> None:
        from nanobot.config.schema import AgentDefaults

        assert AgentDefaults().microcompact_tool_results is True

    def test_schema_accepts_camel_case_disable(self) -> None:
        from nanobot.config.schema import AgentDefaults

        defaults = AgentDefaults(microcompactToolResults=False)
        assert defaults.microcompact_tool_results is False

    def test_loop_propagates_disable_to_execution_components(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, microcompact_tool_results=False)

        assert loop.microcompact_tool_results is False
        assert loop.consolidator.microcompact_tool_results is False
        assert loop.subagents.microcompact_tool_results is False
