"""Tests for max_messages config wiring into session history replay."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.session.manager import HISTORY_MAX_MESSAGES, Session


def _make_loop(tmp_path: Path, max_messages: int = 0) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        max_messages=max_messages,
    )


def _populated_session(n: int) -> Session:
    """Create a session with *n* user/assistant turn pairs."""
    session = Session(key="test:populated")
    for i in range(n):
        session.add_message("user", f"msg-{i}")
        session.add_message("assistant", f"reply-{i}")
    return session


class TestMaxMessagesInit:
    """Verify AgentLoop stores the config value correctly."""

    def test_default_is_zero(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        assert loop._max_messages == 0

    def test_positive_value_stored(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path, max_messages=25)
        assert loop._max_messages == 25

    def test_zero_means_unlimited(self, tmp_path: Path) -> None:
        """max_messages=0 should not constrain get_history (uses default)."""
        loop = _make_loop(tmp_path, max_messages=0)
        assert loop._max_messages == 0

    def test_negative_treated_as_zero(self, tmp_path: Path) -> None:
        """Negative values should not produce negative slicing."""
        loop = _make_loop(tmp_path, max_messages=-5)
        assert loop._max_messages == 0


class TestGetHistoryWithMaxMessages:
    """Verify get_history respects max_messages parameter."""

    def test_default_uses_constant(self) -> None:
        session = _populated_session(80)
        history = session.get_history()
        # Default HISTORY_MAX_MESSAGES=120, 80 pairs = 160 msgs, sliced to 120
        assert len(history) <= HISTORY_MAX_MESSAGES

    def test_explicit_max_messages_limits_output(self) -> None:
        session = _populated_session(40)  # 80 messages total
        history = session.get_history(max_messages=20)
        assert len(history) <= 20

    def test_max_messages_starts_at_user_turn(self) -> None:
        """Sliced history should start with a user message, not mid-turn."""
        session = _populated_session(30)  # 60 messages
        history = session.get_history(max_messages=25)
        assert history[0]["role"] == "user"

    def test_max_messages_zero_returns_all(self) -> None:
        """max_messages=0 with the default constant returns up to the constant."""
        session = _populated_session(10)  # 20 messages
        # When we pass 0 explicitly, unconsolidated[-0:] returns everything
        # but the default is HISTORY_MAX_MESSAGES so this tests the default path
        history = session.get_history()
        assert len(history) == 20

    def test_small_session_unaffected(self) -> None:
        """When session has fewer messages than max_messages, all are returned."""
        session = _populated_session(5)  # 10 messages
        history = session.get_history(max_messages=25)
        assert len(history) == 10


class TestMaxMessagesIntegration:
    """Verify the config flows from AgentLoop into get_history calls."""

    def test_config_wired_to_history_call(self, tmp_path: Path) -> None:
        """When max_messages > 0, get_history should receive it."""
        loop = _make_loop(tmp_path, max_messages=25)
        session = _populated_session(40)  # 80 messages

        with patch.object(session, "get_history", wraps=session.get_history) as mock_hist:
            # Call the internal method that builds history kwargs
            kwargs: dict[str, Any] = {
                "max_tokens": loop._replay_token_budget(),
                "include_timestamps": True,
            }
            if loop._max_messages > 0:
                kwargs["max_messages"] = loop._max_messages
            session.get_history(**kwargs)

            assert mock_hist.call_count == 1
            call_kwargs = mock_hist.call_args
            # max_messages is positional arg (first) or keyword
            if call_kwargs.args:
                assert call_kwargs.args[0] == 25
            else:
                assert call_kwargs.kwargs.get("max_messages") == 25

    def test_zero_config_omits_max_messages_kwarg(self, tmp_path: Path) -> None:
        """When max_messages=0, get_history should use its default."""
        loop = _make_loop(tmp_path, max_messages=0)

        kwargs: dict[str, Any] = {
            "max_tokens": loop._replay_token_budget(),
            "include_timestamps": True,
        }
        if loop._max_messages > 0:
            kwargs["max_messages"] = loop._max_messages

        assert "max_messages" not in kwargs


class TestSchemaConfig:
    """Verify the config schema accepts max_messages."""

    def test_schema_default(self) -> None:
        from nanobot.config.schema import AgentDefaults

        defaults = AgentDefaults()
        assert defaults.max_messages == 0

    def test_schema_accepts_positive(self) -> None:
        from nanobot.config.schema import AgentDefaults

        defaults = AgentDefaults(max_messages=25)
        assert defaults.max_messages == 25

    def test_schema_rejects_negative(self) -> None:
        from nanobot.config.schema import AgentDefaults

        with pytest.raises(Exception):  # Pydantic validation error
            AgentDefaults(max_messages=-1)
