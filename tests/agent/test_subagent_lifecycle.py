"""Tests for SubagentManager lifecycle — spawn, run, announce, cancel."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import (
    SubagentManager,
    SubagentStatus,
    _SubagentHook,
)
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manager(tmp_path: Path, **kw) -> SubagentManager:
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test-model"
    defaults = dict(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test-model",
        max_tool_result_chars=16_000,
    )
    defaults.update(kw)
    return SubagentManager(**defaults)


def _make_hook_context(**overrides) -> AgentHookContext:
    defaults = dict(
        iteration=1,
        tool_calls=[],
        tool_events=[],
        messages=[],
        usage={},
        error=None,
        stop_reason="completed",
        final_content="ok",
    )
    defaults.update(overrides)
    return AgentHookContext(**defaults)


# ---------------------------------------------------------------------------
# SubagentStatus defaults
# ---------------------------------------------------------------------------


class TestSubagentStatus:
    def test_defaults(self):
        s = SubagentStatus(
            task_id="abc", label="test", task_description="do stuff",
            started_at=time.monotonic(),
        )
        assert s.phase == "initializing"
        assert s.iteration == 0
        assert s.tool_events == []
        assert s.usage == {}
        assert s.stop_reason is None
        assert s.error is None


# ---------------------------------------------------------------------------
# set_provider
# ---------------------------------------------------------------------------


class TestSetProvider:
    def test_updates_provider_model_runner(self, tmp_path):
        sm = _manager(tmp_path)
        new_provider = MagicMock(spec=LLMProvider)
        sm.set_provider(new_provider, "new-model")
        assert sm.provider is new_provider
        assert sm.model == "new-model"
        assert sm.runner.provider is new_provider


# ---------------------------------------------------------------------------
# spawn
# ---------------------------------------------------------------------------


class TestSpawn:
    @pytest.mark.asyncio
    async def test_returns_string_with_task_id(self, tmp_path):
        sm = _manager(tmp_path)
        sm.runner.run = AsyncMock(return_value=AgentRunResult(
            final_content="done", messages=[], stop_reason="completed",
        ))
        result = await sm.spawn("do something")
        assert "started" in result
        assert "id:" in result

    @pytest.mark.asyncio
    async def test_creates_task_in_running_tasks(self, tmp_path):
        sm = _manager(tmp_path)
        block = asyncio.Event()
        async def _slow_run(spec):
            await block.wait()
            return AgentRunResult(final_content="done", messages=[], stop_reason="completed")
        sm.runner.run = _slow_run

        await sm.spawn("task", session_key="s1")
        assert len(sm._running_tasks) == 1

        block.set()
        await asyncio.sleep(0.1)
        assert len(sm._running_tasks) == 0

    @pytest.mark.asyncio
    async def test_creates_status(self, tmp_path):
        sm = _manager(tmp_path)
        sm.runner.run = AsyncMock(return_value=AgentRunResult(
            final_content="done", messages=[], stop_reason="completed",
        ))
        await sm.spawn("my task")
        await asyncio.sleep(0.1)
        # Status cleaned up after task completes
        assert len(sm._task_statuses) == 0

    @pytest.mark.asyncio
    async def test_registers_in_session_tasks(self, tmp_path):
        sm = _manager(tmp_path)
        block = asyncio.Event()
        async def _slow_run(spec):
            await block.wait()
            return AgentRunResult(final_content="done", messages=[], stop_reason="completed")
        sm.runner.run = _slow_run

        await sm.spawn("task", session_key="s1")
        assert "s1" in sm._session_tasks
        assert len(sm._session_tasks["s1"]) == 1

        block.set()
        await asyncio.sleep(0.1)
        assert "s1" not in sm._session_tasks

    @pytest.mark.asyncio
    async def test_no_session_key_no_registration(self, tmp_path):
        sm = _manager(tmp_path)
        block = asyncio.Event()
        async def _slow_run(spec):
            await block.wait()
            return AgentRunResult(final_content="done", messages=[], stop_reason="completed")
        sm.runner.run = _slow_run

        await sm.spawn("task")
        assert len(sm._session_tasks) == 0

        block.set()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_label_defaults_to_truncated_task(self, tmp_path):
        sm = _manager(tmp_path)
        block = asyncio.Event()
        async def _slow_run(spec):
            await block.wait()
            return AgentRunResult(final_content="done", messages=[], stop_reason="completed")
        sm.runner.run = _slow_run

        long_task = "A" * 50
        await sm.spawn(long_task, session_key="s1")
        status = next(iter(sm._task_statuses.values()))
        assert status.label == long_task[:30] + "..."

        block.set()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_custom_label(self, tmp_path):
        sm = _manager(tmp_path)
        block = asyncio.Event()
        async def _slow_run(spec):
            await block.wait()
            return AgentRunResult(final_content="done", messages=[], stop_reason="completed")
        sm.runner.run = _slow_run

        await sm.spawn("task", label="Custom Label", session_key="s1")
        status = next(iter(sm._task_statuses.values()))
        assert status.label == "Custom Label"

        block.set()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_cleanup_callback_removes_all_entries(self, tmp_path):
        sm = _manager(tmp_path)
        sm.runner.run = AsyncMock(return_value=AgentRunResult(
            final_content="done", messages=[], stop_reason="completed",
        ))
        await sm.spawn("task", session_key="s1")
        await asyncio.sleep(0.1)
        assert len(sm._running_tasks) == 0
        assert len(sm._task_statuses) == 0
        assert len(sm._session_tasks) == 0


# ---------------------------------------------------------------------------
# _run_subagent
# ---------------------------------------------------------------------------


class TestRunSubagent:
    @pytest.mark.asyncio
    async def test_successful_run(self, tmp_path):
        sm = _manager(tmp_path)
        sm.runner.run = AsyncMock(return_value=AgentRunResult(
            final_content="Task done!", messages=[], stop_reason="completed",
        ))
        with patch.object(sm, "_announce_result", new_callable=AsyncMock) as mock_announce:
            await sm._run_subagent(
                "t1", "do task", "label",
                {"channel": "cli", "chat_id": "direct"},
                SubagentStatus(task_id="t1", label="label", task_description="do task", started_at=time.monotonic()),
            )
            mock_announce.assert_called_once()
            assert mock_announce.call_args.args[-2] == "ok"

    @pytest.mark.asyncio
    async def test_tool_error_run(self, tmp_path):
        sm = _manager(tmp_path)
        sm.runner.run = AsyncMock(return_value=AgentRunResult(
            final_content=None, messages=[], stop_reason="tool_error",
            tool_events=[{"name": "read_file", "status": "error", "detail": "not found"}],
        ))
        status = SubagentStatus(task_id="t1", label="label", task_description="do task", started_at=time.monotonic())
        with patch.object(sm, "_announce_result", new_callable=AsyncMock) as mock_announce:
            await sm._run_subagent(
                "t1", "do task", "label",
                {"channel": "cli", "chat_id": "direct"}, status,
            )
            assert mock_announce.call_args.args[-2] == "error"

    @pytest.mark.asyncio
    async def test_exception_run(self, tmp_path):
        sm = _manager(tmp_path)
        sm.runner.run = AsyncMock(side_effect=RuntimeError("LLM down"))
        status = SubagentStatus(task_id="t1", label="label", task_description="do task", started_at=time.monotonic())
        with patch.object(sm, "_announce_result", new_callable=AsyncMock) as mock_announce:
            await sm._run_subagent(
                "t1", "do task", "label",
                {"channel": "cli", "chat_id": "direct"}, status,
            )
            assert status.phase == "error"
            assert "LLM down" in status.error
            assert mock_announce.call_args.args[-2] == "error"

    @pytest.mark.asyncio
    async def test_status_updated_on_success(self, tmp_path):
        sm = _manager(tmp_path)
        sm.runner.run = AsyncMock(return_value=AgentRunResult(
            final_content="ok", messages=[], stop_reason="completed",
        ))
        status = SubagentStatus(task_id="t1", label="label", task_description="do task", started_at=time.monotonic())
        with patch.object(sm, "_announce_result", new_callable=AsyncMock):
            await sm._run_subagent(
                "t1", "do task", "label",
                {"channel": "cli", "chat_id": "direct"}, status,
            )
            assert status.phase == "done"
            assert status.stop_reason == "completed"


# ---------------------------------------------------------------------------
# _announce_result
# ---------------------------------------------------------------------------


class TestAnnounceResult:
    @pytest.mark.asyncio
    async def test_publishes_inbound_message(self, tmp_path):
        sm = _manager(tmp_path)
        published = []
        sm.bus.publish_inbound = AsyncMock(side_effect=lambda msg: published.append(msg))

        await sm._announce_result(
            "t1", "label", "task", "result text",
            {"channel": "cli", "chat_id": "direct"}, "ok",
        )

        assert len(published) == 1
        msg = published[0]
        assert msg.channel == "system"
        assert msg.sender_id == "subagent"
        assert msg.metadata["injected_event"] == "subagent_result"
        assert msg.metadata["subagent_task_id"] == "t1"

    @pytest.mark.asyncio
    async def test_session_key_override(self, tmp_path):
        sm = _manager(tmp_path)
        published = []
        sm.bus.publish_inbound = AsyncMock(side_effect=lambda msg: published.append(msg))

        await sm._announce_result(
            "t1", "label", "task", "result",
            {"channel": "telegram", "chat_id": "123", "session_key": "s1"}, "ok",
        )

        assert published[0].session_key_override == "s1"

    @pytest.mark.asyncio
    async def test_session_key_override_fallback(self, tmp_path):
        sm = _manager(tmp_path)
        published = []
        sm.bus.publish_inbound = AsyncMock(side_effect=lambda msg: published.append(msg))

        await sm._announce_result(
            "t1", "label", "task", "result",
            {"channel": "telegram", "chat_id": "123"}, "ok",
        )

        assert published[0].session_key_override == "telegram:123"

    @pytest.mark.asyncio
    async def test_ok_status_text(self, tmp_path):
        sm = _manager(tmp_path)
        published = []
        sm.bus.publish_inbound = AsyncMock(side_effect=lambda msg: published.append(msg))

        await sm._announce_result(
            "t1", "label", "task", "result",
            {"channel": "cli", "chat_id": "direct"}, "ok",
        )

        assert "completed successfully" in published[0].content

    @pytest.mark.asyncio
    async def test_error_status_text(self, tmp_path):
        sm = _manager(tmp_path)
        published = []
        sm.bus.publish_inbound = AsyncMock(side_effect=lambda msg: published.append(msg))

        await sm._announce_result(
            "t1", "label", "task", "error details",
            {"channel": "cli", "chat_id": "direct"}, "error",
        )

        assert "failed" in published[0].content

    @pytest.mark.asyncio
    async def test_origin_message_id_in_metadata(self, tmp_path):
        sm = _manager(tmp_path)
        published = []
        sm.bus.publish_inbound = AsyncMock(side_effect=lambda msg: published.append(msg))

        await sm._announce_result(
            "t1", "label", "task", "result",
            {"channel": "cli", "chat_id": "direct"}, "ok",
            origin_message_id="msg-123",
        )

        assert published[0].metadata["origin_message_id"] == "msg-123"


# ---------------------------------------------------------------------------
# _format_partial_progress
# ---------------------------------------------------------------------------


class TestFormatPartialProgress:
    def _make_result(self, tool_events=None, error=None):
        return MagicMock(tool_events=tool_events or [], error=error)

    def test_completed_only(self):
        result = self._make_result(tool_events=[
            {"name": "read_file", "status": "ok", "detail": "file content"},
            {"name": "exec", "status": "ok", "detail": "output"},
        ])
        text = SubagentManager._format_partial_progress(result)
        assert "Completed steps:" in text
        assert "read_file" in text
        assert "exec" in text

    def test_failure_only(self):
        result = self._make_result(tool_events=[
            {"name": "read_file", "status": "error", "detail": "not found"},
        ])
        text = SubagentManager._format_partial_progress(result)
        assert "Failure:" in text
        assert "not found" in text

    def test_completed_and_failure(self):
        result = self._make_result(tool_events=[
            {"name": "read_file", "status": "ok", "detail": "content"},
            {"name": "exec", "status": "error", "detail": "timeout"},
        ])
        text = SubagentManager._format_partial_progress(result)
        assert "Completed steps:" in text
        assert "Failure:" in text

    def test_limited_to_last_three(self):
        result = self._make_result(tool_events=[
            {"name": f"tool_{i}", "status": "ok", "detail": f"result_{i}"}
            for i in range(5)
        ])
        text = SubagentManager._format_partial_progress(result)
        assert "tool_2" in text
        assert "tool_3" in text
        assert "tool_4" in text
        assert "tool_0" not in text
        assert "tool_1" not in text

    def test_error_without_failure_event(self):
        result = self._make_result(
            tool_events=[{"name": "read_file", "status": "ok", "detail": "ok"}],
            error="Something went wrong",
        )
        text = SubagentManager._format_partial_progress(result)
        assert "Something went wrong" in text

    def test_empty_events_with_error(self):
        result = self._make_result(error="Total failure")
        text = SubagentManager._format_partial_progress(result)
        assert "Total failure" in text

    def test_empty_no_error_returns_fallback(self):
        result = self._make_result()
        text = SubagentManager._format_partial_progress(result)
        assert "Error" in text


# ---------------------------------------------------------------------------
# cancel_by_session
# ---------------------------------------------------------------------------


class TestCancelBySession:
    @pytest.mark.asyncio
    async def test_cancels_running_tasks(self, tmp_path):
        sm = _manager(tmp_path)
        block = asyncio.Event()
        async def _slow_run(spec):
            await block.wait()
            return AgentRunResult(final_content="done", messages=[], stop_reason="completed")
        sm.runner.run = _slow_run

        await sm.spawn("task1", session_key="s1")
        await sm.spawn("task2", session_key="s1")
        assert len(sm._session_tasks.get("s1", set())) == 2

        count = await sm.cancel_by_session("s1")
        assert count == 2
        block.set()
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_no_tasks_returns_zero(self, tmp_path):
        sm = _manager(tmp_path)
        count = await sm.cancel_by_session("nonexistent")
        assert count == 0

    @pytest.mark.asyncio
    async def test_already_done_not_counted(self, tmp_path):
        sm = _manager(tmp_path)
        sm.runner.run = AsyncMock(return_value=AgentRunResult(
            final_content="done", messages=[], stop_reason="completed",
        ))
        await sm.spawn("task1", session_key="s1")
        await asyncio.sleep(0.1)  # Wait for completion

        count = await sm.cancel_by_session("s1")
        assert count == 0


# ---------------------------------------------------------------------------
# get_running_count / get_running_count_by_session
# ---------------------------------------------------------------------------


class TestRunningCounts:
    @pytest.mark.asyncio
    async def test_running_count_zero(self, tmp_path):
        sm = _manager(tmp_path)
        assert sm.get_running_count() == 0

    @pytest.mark.asyncio
    async def test_running_count_tracks_tasks(self, tmp_path):
        sm = _manager(tmp_path)
        block = asyncio.Event()
        async def _slow_run(spec):
            await block.wait()
            return AgentRunResult(final_content="done", messages=[], stop_reason="completed")
        sm.runner.run = _slow_run

        await sm.spawn("t1", session_key="s1")
        await sm.spawn("t2", session_key="s1")
        assert sm.get_running_count() == 2
        assert sm.get_running_count_by_session("s1") == 2

        block.set()
        await asyncio.sleep(0.1)
        assert sm.get_running_count() == 0

    @pytest.mark.asyncio
    async def test_running_count_by_session_nonexistent(self, tmp_path):
        sm = _manager(tmp_path)
        assert sm.get_running_count_by_session("nonexistent") == 0


# ---------------------------------------------------------------------------
# _SubagentHook
# ---------------------------------------------------------------------------


class TestSubagentHook:
    @pytest.mark.asyncio
    async def test_before_execute_tools_logs(self, tmp_path):
        hook = _SubagentHook("t1")
        tool_call = MagicMock()
        tool_call.name = "read_file"
        tool_call.arguments = {"path": "/tmp/test"}
        ctx = _make_hook_context(tool_calls=[tool_call])
        # Should not raise
        await hook.before_execute_tools(ctx)

    @pytest.mark.asyncio
    async def test_after_iteration_updates_status(self):
        status = SubagentStatus(
            task_id="t1", label="test", task_description="do", started_at=time.monotonic(),
        )
        hook = _SubagentHook("t1", status)
        ctx = _make_hook_context(
            iteration=3,
            tool_events=[{"name": "read_file", "status": "ok", "detail": ""}],
            usage={"prompt_tokens": 100},
        )
        await hook.after_iteration(ctx)
        assert status.iteration == 3
        assert len(status.tool_events) == 1
        assert status.usage == {"prompt_tokens": 100}

    @pytest.mark.asyncio
    async def test_after_iteration_no_status_noop(self):
        hook = _SubagentHook("t1", status=None)
        ctx = _make_hook_context(iteration=5)
        # Should not raise
        await hook.after_iteration(ctx)

    @pytest.mark.asyncio
    async def test_after_iteration_sets_error(self):
        status = SubagentStatus(
            task_id="t1", label="test", task_description="do", started_at=time.monotonic(),
        )
        hook = _SubagentHook("t1", status)
        ctx = _make_hook_context(error="something broke")
        await hook.after_iteration(ctx)
        assert status.error == "something broke"
