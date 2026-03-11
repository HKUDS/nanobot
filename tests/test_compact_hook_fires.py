"""Tests that memory consolidation fires the message.compact hook for OpenViking."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import nanobot.agent.memory as memory_module
from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryConsolidator, MemoryStore
from nanobot.bus.queue import MessageBus
from nanobot.hooks.base import Hook, HookContext
from nanobot.providers.base import LLMResponse
from nanobot.session.manager import Session, SessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(tmp_path: Path, *, context_window_tokens: int = 1) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.estimate_prompt_tokens.return_value = (10_000, "test")
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(content="ok", tool_calls=[])
    )
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=context_window_tokens,
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


async def _noop_build_messages(**kwargs):
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# MemoryConsolidator callback tests
# ---------------------------------------------------------------------------


class TestOnConsolidatedCallback:
    """Verify the on_consolidated callback fires at the right time."""

    @pytest.mark.asyncio
    async def test_callback_called_on_success(self, tmp_path: Path) -> None:
        """on_consolidated is invoked after a successful consolidation."""
        received: list[tuple] = []

        async def _on_consolidated(messages, session_key):
            received.append((messages, session_key))

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=MagicMock(),
            model="test",
            sessions=SessionManager(tmp_path),
            context_window_tokens=1,
            build_messages=_noop_build_messages,
            get_tool_definitions=lambda: [],
            on_consolidated=_on_consolidated,
        )
        consolidator.store.consolidate = AsyncMock(return_value=True)

        msgs = [{"role": "user", "content": "hello"}]
        result = await consolidator.consolidate_messages(msgs, session_key="test:key")

        assert result is True
        assert len(received) == 1
        assert received[0][0] is msgs
        assert received[0][1] == "test:key"

    @pytest.mark.asyncio
    async def test_callback_not_called_on_failure(self, tmp_path: Path) -> None:
        """on_consolidated is NOT invoked when consolidation fails."""
        received: list[tuple] = []

        async def _on_consolidated(messages, session_key):
            received.append((messages, session_key))

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=MagicMock(),
            model="test",
            sessions=SessionManager(tmp_path),
            context_window_tokens=1,
            build_messages=_noop_build_messages,
            get_tool_definitions=lambda: [],
            on_consolidated=_on_consolidated,
        )
        consolidator.store.consolidate = AsyncMock(return_value=False)

        msgs = [{"role": "user", "content": "hello"}]
        result = await consolidator.consolidate_messages(msgs, session_key="test:key")

        assert result is False
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_callback_none_is_harmless(self, tmp_path: Path) -> None:
        """No crash when on_consolidated is None (default)."""
        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=MagicMock(),
            model="test",
            sessions=SessionManager(tmp_path),
            context_window_tokens=1,
            build_messages=_noop_build_messages,
            get_tool_definitions=lambda: [],
        )
        consolidator.store.consolidate = AsyncMock(return_value=True)

        result = await consolidator.consolidate_messages(
            [{"role": "user", "content": "hi"}], session_key="x",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_callback_error_does_not_break_consolidation(self, tmp_path: Path) -> None:
        """A failing callback does not prevent consolidate_messages from returning True."""
        async def _broken_callback(messages, session_key):
            raise RuntimeError("boom")

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=MagicMock(),
            model="test",
            sessions=SessionManager(tmp_path),
            context_window_tokens=1,
            build_messages=_noop_build_messages,
            get_tool_definitions=lambda: [],
            on_consolidated=_broken_callback,
        )
        consolidator.store.consolidate = AsyncMock(return_value=True)

        result = await consolidator.consolidate_messages(
            [{"role": "user", "content": "hi"}], session_key="x",
        )
        assert result is True


# ---------------------------------------------------------------------------
# AgentLoop integration: compact hook fires after consolidation
# ---------------------------------------------------------------------------


class _SpyCompactHook(Hook):
    """Test hook that records calls."""

    name = "spy_compact"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, context: HookContext, **kwargs) -> dict:
        self.calls.append({
            "session_key": context.session_key,
            "messages": kwargs.get("session").messages if kwargs.get("session") else [],
        })
        return {"success": True}


class TestCompactHookFiringFromLoop:
    """Verify that AgentLoop._fire_compact_hook is wired to MemoryConsolidator."""

    @pytest.mark.asyncio
    async def test_compact_hook_fires_on_archive_unconsolidated(self, tmp_path: Path) -> None:
        """The message.compact hook fires when /new archives session messages."""
        from nanobot.bus.events import InboundMessage

        loop = _make_loop(tmp_path)
        spy = _SpyCompactHook()
        loop.hook_manager.register("message.compact", spy)

        session = loop.sessions.get_or_create("cli:test")
        for i in range(5):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        loop.sessions.save(session)

        loop.memory_consolidator.store.consolidate = AsyncMock(return_value=True)

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(msg)

        assert response is not None
        assert "new session started" in response.content.lower()
        assert len(spy.calls) == 1
        assert spy.calls[0]["session_key"] == "cli:test"
        assert len(spy.calls[0]["messages"]) == 10

    @pytest.mark.asyncio
    async def test_compact_hook_fires_on_token_consolidation(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """The message.compact hook fires during automatic token-based consolidation."""
        loop = _make_loop(tmp_path, context_window_tokens=200)
        spy = _SpyCompactHook()
        loop.hook_manager.register("message.compact", spy)

        session = loop.sessions.get_or_create("cli:test")
        session.messages = [
            {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
            {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
            {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
            {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
            {"role": "user", "content": "u3", "timestamp": "2026-01-01T00:00:04"},
        ]
        loop.sessions.save(session)

        loop.memory_consolidator.store.consolidate = AsyncMock(return_value=True)

        call_count = [0]
        async def mock_estimate(_session):
            call_count[0] += 1
            return (500 if call_count[0] <= 1 else 80, "test")
        loop.memory_consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]
        monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 100)

        await loop.memory_consolidator.maybe_consolidate_by_tokens(session)

        assert len(spy.calls) >= 1
        assert spy.calls[0]["session_key"] == "cli:test"

    @pytest.mark.asyncio
    async def test_compact_hook_not_fired_when_no_hooks_registered(
        self, tmp_path: Path,
    ) -> None:
        """No error when message.compact has no hooks registered."""
        loop = _make_loop(tmp_path)
        assert not loop.hook_manager.has_hooks("message.compact")

        session = loop.sessions.get_or_create("cli:test")
        for i in range(3):
            session.add_message("user", f"msg{i}")
        loop.sessions.save(session)

        loop.memory_consolidator.store.consolidate = AsyncMock(return_value=True)

        result = await loop.memory_consolidator.archive_unconsolidated(session)
        assert result is True

    @pytest.mark.asyncio
    async def test_compact_hook_not_fired_when_consolidation_fails(
        self, tmp_path: Path,
    ) -> None:
        """The hook is not fired if consolidation returns False."""
        from nanobot.bus.events import InboundMessage

        loop = _make_loop(tmp_path)
        spy = _SpyCompactHook()
        loop.hook_manager.register("message.compact", spy)

        session = loop.sessions.get_or_create("cli:test")
        for i in range(3):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        loop.sessions.save(session)

        loop.memory_consolidator.store.consolidate = AsyncMock(return_value=False)

        msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        await loop._process_message(msg)

        assert len(spy.calls) == 0


# ---------------------------------------------------------------------------
# Build-messages await correctness
# ---------------------------------------------------------------------------


class TestBuildMessagesAwait:
    """Verify that build_messages is properly awaited in the agent loop."""

    @pytest.mark.asyncio
    async def test_process_direct_does_not_return_coroutine(self, tmp_path: Path) -> None:
        """process_direct should work end-to-end without 'coroutine never awaited' warnings."""
        loop = _make_loop(tmp_path, context_window_tokens=999_999)
        result = await loop.process_direct("hello", session_key="cli:test")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_build_messages_result_is_list(self, tmp_path: Path) -> None:
        """build_messages returns a list of dicts, not a coroutine."""
        from nanobot.agent.context import ContextBuilder

        ctx = ContextBuilder(tmp_path)
        result = await ctx.build_messages(
            history=[], current_message="test", channel="cli", chat_id="test",
        )
        assert isinstance(result, list)
        assert all(isinstance(m, dict) for m in result)
