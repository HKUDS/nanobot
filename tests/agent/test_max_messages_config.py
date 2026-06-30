"""Tests for the internal max_messages replay cap."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.providers.factory import ProviderSnapshot
from nanobot.session.manager import (
    FILE_MAX_MESSAGES,
    Session,
    replay_max_messages_for_context,
)


def _make_loop(
    tmp_path: Path,
    context_window_tokens: int = 200_000,
) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=context_window_tokens,
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
    """Verify AgentLoop derives the internal replay cap correctly."""

    def test_context_formula(self) -> None:
        assert replay_max_messages_for_context(8_000) == 120
        assert replay_max_messages_for_context(32_768) == 327
        assert replay_max_messages_for_context(200_000) == FILE_MAX_MESSAGES

    def test_default_for_200k_context_reaches_file_cap(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._max_messages == FILE_MAX_MESSAGES

    def test_default_scales_with_context_window(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, context_window_tokens=32_768)
        assert loop._max_messages == 327

    def test_provider_refresh_resyncs_context_derived_limit(self, tmp_path: Path) -> None:
        old_provider = MagicMock()
        old_provider.get_default_model.return_value = "old-model"
        old_provider.generation.max_tokens = 4096
        new_provider = MagicMock()
        new_provider.generation.max_tokens = 4096
        loop = AgentLoop(
            bus=MessageBus(),
            provider=old_provider,
            workspace=tmp_path,
            model="old-model",
            context_window_tokens=32_768,
            provider_snapshot_loader=lambda: ProviderSnapshot(
                provider=new_provider,
                model="new-model",
                context_window_tokens=200_000,
                signature=("new-model",),
            ),
        )

        assert loop._max_messages == 327
        loop._refresh_provider_snapshot()
        assert loop._max_messages == FILE_MAX_MESSAGES


class TestGetHistoryWithMaxMessages:
    """Verify get_history respects max_messages parameter."""

    def test_default_uses_builtin_limit(self) -> None:
        session = _populated_session(80)
        history = session.get_history()
        assert len(history) <= FILE_MAX_MESSAGES

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
        assert len(history) <= FILE_MAX_MESSAGES

    def test_small_session_unaffected(self) -> None:
        """When session has fewer messages than max_messages, all are returned."""
        session = _populated_session(5)  # 10 messages
        history = session.get_history(max_messages=25)
        assert len(history) == 10


class TestMaxMessagesIntegration:
    """Verify AgentLoop passes the replay cap into get_history calls."""

    @pytest.mark.asyncio
    async def test_process_message_passes_limit_to_history_call(self, tmp_path: Path) -> None:
        """The real message path should pass max_messages into session history replay."""
        loop = _make_loop(tmp_path)
        loop._max_messages = 25
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
    async def test_default_limit_passes_context_derived_limit_to_history_call(
        self,
        tmp_path: Path,
    ) -> None:
        loop = _make_loop(tmp_path)
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
        assert mock_hist.call_args.kwargs["max_messages"] == FILE_MAX_MESSAGES
        assert mock_hist.call_args.kwargs["extend_to_user"] is False

    @pytest.mark.asyncio
    async def test_process_message_uses_current_user_as_replay_boundary(
        self,
        tmp_path: Path,
    ) -> None:
        """A live user turn should not extend history to an older long tool turn."""
        loop = _make_loop(tmp_path)
        loop._max_messages = 6
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
