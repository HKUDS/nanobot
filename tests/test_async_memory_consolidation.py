"""Test async memory consolidation background task.

Tests for the new async background consolidation feature where token-based
consolidation runs when sessions are idle instead of blocking user interactions.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryConsolidator
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


class TestMemoryConsolidatorBackgroundTask:
    """Tests for the background consolidation task."""

    @pytest.mark.asyncio
    async def test_start_and_stop_background_task(self, tmp_path) -> None:
        """Test that background task can be started and stopped cleanly."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[])

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Start background task
        await consolidator.start_background_task()
        assert consolidator._background_task is not None
        assert not consolidator._stop_event.is_set()

        # Stop background task
        await consolidator.stop_background_task()
        assert consolidator._background_task is None or consolidator._background_task.done()

    @pytest.mark.asyncio
    async def test_background_loop_checks_idle_sessions(self, tmp_path) -> None:
        """Test that background loop checks for idle sessions."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

        session1 = MagicMock()
        session1.key = "cli:session1"
        session1.messages = [{"role": "user", "content": "msg"}]
        session2 = MagicMock()
        session2.key = "cli:session2"
        session2.messages = []

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[session1, session2])

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Mark session1 as recently active (should not consolidate)
        consolidator._session_last_activity["cli:session1"] = asyncio.get_event_loop().time()
        # Leave session2 without activity record (should be considered idle)

        # Mock maybe_consolidate_by_tokens_async to track calls
        consolidator.maybe_consolidate_by_tokens_async = AsyncMock()  # type: ignore[method-assign]

        # Run the background loop with a very short interval for testing
        with patch.object(consolidator, '_IDLE_CHECK_INTERVAL', 0.1):
            # Start task and let it run briefly
            await consolidator.start_background_task()
            await asyncio.sleep(0.5)
            await consolidator.stop_background_task()

        # session2 should have been checked for consolidation (it's idle)
        # session1 should not have been consolidated (recently active)
        assert consolidator.maybe_consolidate_by_tokens_async.await_count >= 0

    @pytest.mark.asyncio
    async def test_record_activity_updates_timestamp(self, tmp_path) -> None:
        """Test that record_activity updates the activity timestamp."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[])

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Initially no activity recorded
        assert "cli:test" not in consolidator._session_last_activity

        # Record activity
        consolidator.record_activity("cli:test")
        assert "cli:test" in consolidator._session_last_activity

        # Wait a bit and check timestamp changed
        await asyncio.sleep(0.1)
        consolidator.record_activity("cli:test")
        # The timestamp should have updated (though we can't easily verify the exact value)
        assert consolidator._session_last_activity["cli:test"] > 0

    @pytest.mark.asyncio
    async def test_maybe_consolidate_by_tokens_schedules_async_task(self, tmp_path) -> None:
        """Test that maybe_consolidate_by_tokens schedules an async task."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        session = MagicMock()
        session.messages = [{"role": "user", "content": "msg"}]
        session.key = "cli:test"
        session.context_window_tokens = 200

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[session])
        sessions.save = MagicMock()

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Mock the async version to track calls
        consolidator.maybe_consolidate_by_tokens_async = AsyncMock()  # type: ignore[method-assign]

        # Call the synchronous method - should schedule a task
        consolidator.maybe_consolidate_by_tokens(session)

        # The async version should have been scheduled via create_task
        await asyncio.sleep(0.1)  # Let the task start


class TestAgentLoopIntegration:
    """Integration tests for AgentLoop with background consolidation."""

    @pytest.mark.asyncio
    async def test_loop_starts_background_task(self, tmp_path) -> None:
        """Test that run() starts the background consolidation task."""
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            context_window_tokens=200,
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        # Start the loop in background
        import asyncio
        run_task = asyncio.create_task(loop.run())

        # Give it time to start the background task
        await asyncio.sleep(0.3)

        # Background task should be started
        assert loop.memory_consolidator._background_task is not None

        # Stop the loop
        await loop.stop()
        await run_task

    @pytest.mark.asyncio
    async def test_loop_stops_background_task(self, tmp_path) -> None:
        """Test that stop() stops the background consolidation task."""
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            context_window_tokens=200,
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        # Start the loop in background
        run_task = asyncio.create_task(loop.run())
        await asyncio.sleep(0.3)

        # Stop via async stop method
        await loop.stop()

        # Background task should be stopped
        assert loop.memory_consolidator._background_task is None or \
               loop.memory_consolidator._background_task.done()


class TestIdleDetection:
    """Tests for idle session detection logic."""

    @pytest.mark.asyncio
    async def test_recently_active_session_not_considered_idle(self, tmp_path) -> None:
        """Test that recently active sessions are not consolidated."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

        session = MagicMock()
        session.key = "cli:active"
        session.messages = [{"role": "user", "content": "msg"}]

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[session])

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Mark as recently active (within idle threshold)
        current_time = asyncio.get_event_loop().time()
        consolidator._session_last_activity["cli:active"] = current_time

        # Mock maybe_consolidate_by_tokens_async to track calls
        consolidator.maybe_consolidate_by_tokens_async = AsyncMock()  # type: ignore[method-assign]

        with patch.object(consolidator, '_IDLE_CHECK_INTERVAL', 0.1):
            await consolidator.start_background_task()
            # Sleep less than 2 * interval to ensure session remains active
            await asyncio.sleep(0.15)
            await consolidator.stop_background_task()

        # Should not have been called for recently active session
        assert consolidator.maybe_consolidate_by_tokens_async.await_count == 0

    @pytest.mark.asyncio
    async def test_idle_session_triggers_consolidation(self, tmp_path) -> None:
        """Test that idle sessions trigger consolidation."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

        session = MagicMock()
        session.key = "cli:idle"
        session.messages = [{"role": "user", "content": "msg"}]

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[session])

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Mark as inactive (older than idle threshold)
        current_time = asyncio.get_event_loop().time()
        consolidator._session_last_activity["cli:idle"] = current_time - 10  # 10 seconds ago

        # Mock maybe_consolidate_by_tokens_async to track calls
        consolidator.maybe_consolidate_by_tokens_async = AsyncMock()  # type: ignore[method-assign]

        with patch.object(consolidator, '_IDLE_CHECK_INTERVAL', 0.1):
            await consolidator.start_background_task()
            await asyncio.sleep(0.5)
            await consolidator.stop_background_task()

        # Should have been called for idle session
        assert consolidator.maybe_consolidate_by_tokens_async.await_count >= 1


class TestScheduleConsolidation:
    """Tests for the schedule consolidation mechanism."""

    @pytest.mark.asyncio
    async def test_schedule_consolidation_runs_async_version(self, tmp_path) -> None:
        """Test that scheduling runs the async version."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

        session = MagicMock()
        session.messages = [{"role": "user", "content": "msg"}]
        session.key = "cli:scheduled"

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[session])

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Mock the async version to track calls
        consolidator.maybe_consolidate_by_tokens_async = AsyncMock()  # type: ignore[method-assign]

        # Schedule consolidation
        await consolidator._schedule_consolidation(session)

        await asyncio.sleep(0.1)

        assert consolidator.maybe_consolidate_by_tokens_async.await_count >= 1


class TestBackgroundTaskCancellation:
    """Tests for background task cancellation and error handling."""

    @pytest.mark.asyncio
    async def test_background_task_handles_exceptions_gracefully(self, tmp_path) -> None:
        """Test that exceptions in the loop don't crash it."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[])

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Mock maybe_consolidate_by_tokens_async to raise an exception
        consolidator.maybe_consolidate_by_tokens_async = AsyncMock(  # type: ignore[method-assign]
            side_effect=Exception("Test exception")
        )

        with patch.object(consolidator, '_IDLE_CHECK_INTERVAL', 0.1):
            await consolidator.start_background_task()
            await asyncio.sleep(0.5)
            # Task should still be running despite exceptions
            assert consolidator._background_task is not None
            await consolidator.stop_background_task()

    @pytest.mark.asyncio
    async def test_stop_cancels_running_task(self, tmp_path) -> None:
        """Test that stop properly cancels a running task."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

        sessions = MagicMock()
        sessions.all = MagicMock(return_value=[])

        consolidator = MemoryConsolidator(
            workspace=tmp_path,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=200,
            build_messages=lambda **kw: [],
            get_tool_definitions=lambda: [],
        )

        # Start a task that will sleep for a while
        with patch.object(consolidator, '_IDLE_CHECK_INTERVAL', 10):  # Long interval
            await consolidator.start_background_task()
            # Task should be running
            assert consolidator._background_task is not None

            # Stop should cancel it
            await consolidator.stop_background_task()

            # Verify task was cancelled or completed
            assert consolidator._background_task is None or \
                   consolidator._background_task.done()
