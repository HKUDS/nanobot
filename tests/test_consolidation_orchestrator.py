"""Tests for the rewritten ConsolidationOrchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.consolidation import ConsolidationOrchestrator


def _make_orchestrator(archive_fn=None, memory_window=50, enable_contradiction_check=True):
    memory = MagicMock()
    memory.consolidate = AsyncMock(return_value=True)
    if archive_fn is None:
        archive_fn = MagicMock()
    return (
        ConsolidationOrchestrator(
            memory=memory,
            archive_fn=archive_fn,
            max_concurrent=3,
            memory_window=memory_window,
            enable_contradiction_check=enable_contradiction_check,
        ),
        memory,
        archive_fn,
    )


class TestContextManager:
    async def test_must_be_used_as_context_manager(self):
        orch, _, _ = _make_orchestrator()
        with pytest.raises(AssertionError, match="async context manager"):
            orch.submit("key", MagicMock(), MagicMock(), "model")

    async def test_enter_exit_without_tasks(self):
        orch, _, _ = _make_orchestrator()
        async with orch:
            pass  # no tasks — should exit cleanly


class TestSubmit:
    async def test_submit_calls_consolidate(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            orch.submit("session-1", session, provider, "gpt-4")
        memory.consolidate.assert_called_once()

    async def test_submit_deduplicates_same_session(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            orch.submit("session-1", session, provider, "gpt-4")
            orch.submit("session-1", session, provider, "gpt-4")  # duplicate
        # Only one consolidation despite two submit calls
        assert memory.consolidate.call_count == 1

    async def test_submit_different_sessions_both_run(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            orch.submit("session-1", session, provider, "gpt-4")
            orch.submit("session-2", session, provider, "gpt-4")
        assert memory.consolidate.call_count == 2

    async def test_archive_fn_called_when_consolidate_raises(self):
        archive = MagicMock()
        orch, memory, _ = _make_orchestrator(archive_fn=archive)
        memory.consolidate = AsyncMock(side_effect=RuntimeError("fail"))
        session = MagicMock()
        session.messages = [{"role": "user", "content": "hello"}]
        provider = MagicMock()
        async with orch:
            orch.submit("session-1", session, provider, "gpt-4")
        archive.assert_called_once()
        called_messages = archive.call_args[0][0]
        assert isinstance(called_messages, list)


class TestConsolidateAndWait:
    async def test_consolidate_and_wait_returns_true_on_success(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            result = await orch.consolidate_and_wait("s1", session, provider, "gpt-4")
        assert result is True

    async def test_consolidate_and_wait_passes_archive_all(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            await orch.consolidate_and_wait("s1", session, provider, "gpt-4", archive_all=True)
        _call = memory.consolidate.call_args
        assert _call.kwargs.get("archive_all") is True

    async def test_consolidate_and_wait_passes_constructor_injected_values(self):
        orch, memory, _ = _make_orchestrator(memory_window=42, enable_contradiction_check=False)
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            await orch.consolidate_and_wait("s1", session, provider, "gpt-4")
        _call = memory.consolidate.call_args
        assert _call.kwargs["memory_window"] == 42
        assert _call.kwargs["enable_contradiction_check"] is False
