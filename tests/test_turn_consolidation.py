"""Tests for turn-based memory consolidation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.memory import MemoryConsolidator


def _make_consolidator(
    turn_threshold: int = 20,
    context_window_tokens: int = 65_536,
) -> tuple[MemoryConsolidator, MagicMock]:
    """Create a MemoryConsolidator with mocked dependencies."""
    provider = MagicMock()
    sessions = MagicMock()
    mc = MemoryConsolidator(
        workspace=Path("/tmp/test-workspace"),
        provider=provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=context_window_tokens,
        build_messages=lambda **kw: [],
        get_tool_definitions=lambda: [],
        consolidation_turn_threshold=turn_threshold,
    )
    return mc, sessions


def _make_session(user_turns: int) -> MagicMock:
    """Create a mock session with alternating user/assistant messages."""
    messages = []
    for i in range(user_turns):
        messages.append({"role": "user", "content": f"msg {i}"})
        messages.append({"role": "assistant", "content": f"reply {i}"})
    session = MagicMock()
    session.messages = messages
    session.last_consolidated = 0
    session.key = "test:1"
    return session


class TestTurnConsolidation:
    @pytest.mark.asyncio
    async def test_no_consolidation_below_threshold(self):
        """10 user turns with threshold=20 → no consolidation."""
        mc, sessions = _make_consolidator(turn_threshold=20)
        session = _make_session(user_turns=10)

        with patch.object(mc, "consolidate_messages", new_callable=AsyncMock) as mock_cons:
            await mc.maybe_consolidate_by_turns(session)
            mock_cons.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidation_fires_at_threshold(self):
        """20 user turns with threshold=20 → consolidation fires, offset advances."""
        mc, sessions = _make_consolidator(turn_threshold=20)
        session = _make_session(user_turns=20)

        with patch.object(
            mc, "consolidate_messages", new_callable=AsyncMock, return_value=True
        ) as mock_cons:
            await mc.maybe_consolidate_by_turns(session)
            mock_cons.assert_called_once()
            # Offset should have advanced past the consolidated chunk
            assert session.last_consolidated > 0
            sessions.save.assert_called_once_with(session)

    @pytest.mark.asyncio
    async def test_consolidation_boundary_at_midpoint(self):
        """30 user turns → consolidates roughly half (~15 turns worth of messages)."""
        mc, sessions = _make_consolidator(turn_threshold=20)
        session = _make_session(user_turns=30)

        with patch.object(
            mc, "consolidate_messages", new_callable=AsyncMock, return_value=True
        ) as mock_cons:
            await mc.maybe_consolidate_by_turns(session)
            mock_cons.assert_called_once()
            chunk = mock_cons.call_args[0][0]
            user_turns_in_chunk = sum(1 for m in chunk if m.get("role") == "user")
            # Should consolidate ~half (15) of the 30 user turns
            assert 12 <= user_turns_in_chunk <= 18

    @pytest.mark.asyncio
    async def test_threshold_zero_disables(self):
        """threshold=0 → consolidation disabled."""
        mc, sessions = _make_consolidator(turn_threshold=0)
        session = _make_session(user_turns=50)

        with patch.object(mc, "consolidate_messages", new_callable=AsyncMock) as mock_cons:
            await mc.maybe_consolidate_by_turns(session)
            mock_cons.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_op_on_empty_session(self):
        """Empty session → no consolidation."""
        mc, sessions = _make_consolidator(turn_threshold=5)
        session = MagicMock()
        session.messages = []
        session.last_consolidated = 0
        session.key = "test:1"

        with patch.object(mc, "consolidate_messages", new_callable=AsyncMock) as mock_cons:
            await mc.maybe_consolidate_by_turns(session)
            mock_cons.assert_not_called()


class TestThresholdConfigurable:
    def test_config_field_default(self):
        """AgentDefaults has consolidation_turn_threshold with default 20."""
        from nanobot.config.schema import AgentDefaults
        defaults = AgentDefaults()
        assert defaults.consolidation_turn_threshold == 20

    def test_config_field_custom(self):
        """consolidation_turn_threshold can be set via config."""
        from nanobot.config.schema import AgentDefaults
        defaults = AgentDefaults(consolidation_turn_threshold=10)
        assert defaults.consolidation_turn_threshold == 10

    def test_config_camel_case_alias(self):
        """Config accepts camelCase JSON alias."""
        from nanobot.config.schema import AgentDefaults
        defaults = AgentDefaults(**{"consolidationTurnThreshold": 15})
        assert defaults.consolidation_turn_threshold == 15

    def test_threshold_flows_to_consolidator(self):
        """Custom threshold is stored in MemoryConsolidator."""
        mc, _ = _make_consolidator(turn_threshold=42)
        assert mc._turn_threshold == 42
