"""Tests for /stop task cancellation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_loop(*, exec_config=None):
    """Create a minimal AgentLoop with mocked dependencies."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace, exec_config=exec_config)
    return loop, bus


class TestHandleStop:
    @pytest.mark.asyncio
    async def test_stop_no_active_task(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_stop
        from nanobot.command.router import CommandContext

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/stop", loop=loop)
        out = await cmd_stop(ctx)
        assert "No active task" in out.content

    @pytest.mark.asyncio
    async def test_stop_cancels_active_task(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_stop
        from nanobot.command.router import CommandContext

        loop, bus = _make_loop()
        cancelled = asyncio.Event()

        async def slow_task():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = [task]

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/stop", loop=loop)
        out = await cmd_stop(ctx)

        assert cancelled.is_set()
        assert "stopped" in out.content.lower()

    @pytest.mark.asyncio
    async def test_status_includes_subagent_runtime_snapshot(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_status
        from nanobot.command.router import CommandContext

        loop, _ = _make_loop()
        session = SimpleNamespace(
            get_history=lambda max_messages=0: [],
            metadata={"usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "turns": 3}},
        )
        loop.sessions.get_or_create = MagicMock(return_value=session)
        loop.memory_consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(0, "none"))
        loop.subagents.get_running_count_for_session = MagicMock(return_value=1)
        loop.subagents.get_running_count = MagicMock(return_value=3)
        loop.subagents.list_running_for_session = MagicMock(return_value=["fix bug (abcd1234)"])
        loop._last_usage = {"prompt_tokens": 12, "completion_tokens": 34}
        loop.context_window_tokens = 1000
        loop._start_time = 0
        loop.model = "test-model"

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/status")
        ctx = CommandContext(msg=msg, session=session, key=msg.session_key, raw="/status", loop=loop)
        out = await cmd_status(ctx)

        assert "Subagents: 1 in this chat / 3 total" in out.content
        assert "Active subagent tasks:" in out.content
        assert "fix bug (abcd1234)" in out.content
        assert "Session usage: 100 in / 50 out / 150 total (3 turns)" in out.content

    @pytest.mark.asyncio
    async def test_tasks_command_lists_running_subagents(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_tasks
        from nanobot.command.router import CommandContext

        loop, _ = _make_loop()
        loop.subagents.list_running_for_session = MagicMock(
            return_value=["build report (abcd1234)", "analyze logs (efgh5678)"]
        )

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/tasks")
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/tasks", loop=loop)
        out = await cmd_tasks(ctx)

        assert "Active subagent tasks:" in out.content
        assert "build report (abcd1234)" in out.content

    @pytest.mark.asyncio
    async def test_task_command_shows_task_status(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_task
        from nanobot.command.router import CommandContext

        loop, _ = _make_loop()
        loop.subagents.get_task_info_for_session = MagicMock(
            return_value={"id": "abcd1234", "label": "fix", "status": "running"}
        )

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/task abcd1234")
        ctx = CommandContext(
            msg=msg,
            session=None,
            key=msg.session_key,
            raw="/task abcd1234",
            args="abcd1234",
            loop=loop,
        )
        out = await cmd_task(ctx)

        assert "Task 'abcd1234'" in out.content
        assert "- label: fix" in out.content
        assert "- status: running" in out.content

    @pytest.mark.asyncio
    async def test_taskstop_command_stops_running_task(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_task_stop
        from nanobot.command.router import CommandContext

        loop, _ = _make_loop()
        loop.subagents.stop_task_for_session = AsyncMock(return_value=True)

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/taskstop abcd1234")
        ctx = CommandContext(
            msg=msg, session=None, key=msg.session_key, raw="/taskstop abcd1234", args="abcd1234", loop=loop
        )
        out = await cmd_task_stop(ctx)
        assert "stopped" in out.content.lower()

    @pytest.mark.asyncio
    async def test_tasklabel_command_updates_label(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_task_label
        from nanobot.command.router import CommandContext

        loop, _ = _make_loop()
        loop.subagents.update_task_label_for_session = MagicMock(return_value=True)

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/tasklabel abcd1234 New label")
        ctx = CommandContext(
            msg=msg,
            session=None,
            key=msg.session_key,
            raw="/tasklabel abcd1234 New label",
            args="abcd1234 New label",
            loop=loop,
        )
        out = await cmd_task_label(ctx)
        assert "label updated" in out.content.lower()

    @pytest.mark.asyncio
    async def test_stop_cancels_multiple_tasks(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.command.builtin import cmd_stop
        from nanobot.command.router import CommandContext

        loop, bus = _make_loop()
        events = [asyncio.Event(), asyncio.Event()]

        async def slow(idx):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                events[idx].set()
                raise

        tasks = [asyncio.create_task(slow(i)) for i in range(2)]
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = tasks

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/stop", loop=loop)
        out = await cmd_stop(ctx)

        assert all(e.is_set() for e in events)
        assert "2 task" in out.content


class TestDispatch:
    def test_exec_tool_not_registered_when_disabled(self):
        from nanobot.config.schema import ExecToolConfig

        loop, _bus = _make_loop(exec_config=ExecToolConfig(enable=False))

        assert loop.tools.get("exec") is None

    @pytest.mark.asyncio
    async def test_dispatch_processes_and_publishes(self):
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")
        loop._process_message = AsyncMock(
            return_value=OutboundMessage(channel="test", chat_id="c1", content="hi")
        )
        await loop._dispatch(msg)
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert out.content == "hi"

    @pytest.mark.asyncio
    async def test_dispatch_publishes_post_result_summary_after_final_message(self):
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")
        loop._process_message = AsyncMock(
            return_value=OutboundMessage(
                channel="test",
                chat_id="c1",
                content="final answer",
                metadata={"_tool_summary_line": "Tools used (2): read_file, web_search"},
            )
        )

        await loop._dispatch(msg)
        first = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        second = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

        assert first.content == "final answer"
        assert second.content.startswith("Tools used")
        assert second.metadata["_progress"] is True
        assert second.metadata["_post_result_summary"] is True
        assert second.metadata["_delete_after_s"] == loop._POST_SUMMARY_DELETE_AFTER_S

    @pytest.mark.asyncio
    async def test_dispatch_streaming_preserves_message_metadata(self):
        from nanobot.bus.events import InboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(
            channel="matrix",
            sender_id="u1",
            chat_id="!room:matrix.org",
            content="hello",
            metadata={
                "_wants_stream": True,
                "thread_root_event_id": "$root1",
                "thread_reply_to_event_id": "$reply1",
            },
        )

        async def fake_process(_msg, *, on_stream=None, on_stream_end=None, **kwargs):
            assert on_stream is not None
            assert on_stream_end is not None
            await on_stream("hi")
            await on_stream_end(resuming=False)
            return None

        loop._process_message = fake_process

        await loop._dispatch(msg)
        first = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        second = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

        assert first.metadata["thread_root_event_id"] == "$root1"
        assert first.metadata["thread_reply_to_event_id"] == "$reply1"
        assert first.metadata["_stream_delta"] is True
        assert second.metadata["thread_root_event_id"] == "$root1"
        assert second.metadata["thread_reply_to_event_id"] == "$reply1"
        assert second.metadata["_stream_end"] is True

    @pytest.mark.asyncio
    async def test_processing_lock_serializes(self):
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        order = []

        async def mock_process(m, **kwargs):
            order.append(f"start-{m.content}")
            await asyncio.sleep(0.05)
            order.append(f"end-{m.content}")
            return OutboundMessage(channel="test", chat_id="c1", content=m.content)

        loop._process_message = mock_process
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="a")
        msg2 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="b")

        t1 = asyncio.create_task(loop._dispatch(msg1))
        t2 = asyncio.create_task(loop._dispatch(msg2))
        await asyncio.gather(t1, t2)
        assert order == ["start-a", "end-a", "start-b", "end-b"]


class TestSubagentCancellation:
    @pytest.mark.asyncio
    async def test_cancel_by_session(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)

        cancelled = asyncio.Event()

        async def slow():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow())
        await asyncio.sleep(0)
        mgr._running_tasks["sub-1"] = task
        mgr._session_tasks["test:c1"] = {"sub-1"}

        count = await mgr.cancel_by_session("test:c1")
        assert count == 1
        assert cancelled.is_set()

    @pytest.mark.asyncio
    async def test_cancel_by_session_no_tasks(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)
        assert await mgr.cancel_by_session("nonexistent") == 0

    @pytest.mark.asyncio
    async def test_subagent_running_counts_and_labels_for_session(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)

        t1 = asyncio.create_task(asyncio.sleep(60))
        t2 = asyncio.create_task(asyncio.sleep(60))
        await asyncio.sleep(0)
        mgr._running_tasks["a1"] = t1
        mgr._running_tasks["a2"] = t2
        mgr._session_tasks["test:c1"] = {"a1", "a2"}
        mgr._task_labels["a1"] = "first"
        mgr._task_labels["a2"] = "second"
        mgr._task_created_at["a1"] = 1.0
        mgr._task_created_at["a2"] = 2.0

        assert mgr.get_running_count_for_session("test:c1") == 2
        labels = mgr.list_running_for_session("test:c1", limit=2)
        assert labels == ["second (a2)", "first (a1)"]

        await mgr.cancel_by_session("test:c1")

    @pytest.mark.asyncio
    async def test_subagent_stop_and_update_label_for_session(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)

        task = asyncio.create_task(asyncio.sleep(60))
        await asyncio.sleep(0)
        mgr._running_tasks["a1"] = task
        mgr._session_tasks["test:c1"] = {"a1"}
        mgr._task_session["a1"] = "test:c1"
        mgr._task_labels["a1"] = "old"
        mgr._task_history["a1"] = SimpleNamespace(
            task_id="a1",
            label="old",
            status="running",
            created_at=0.0,
            updated_at=0.0,
            session_key="test:c1",
        )

        assert mgr.update_task_label_for_session("test:c1", "a1", "new") is True
        assert mgr.get_task_info_for_session("test:c1", "a1")["label"] == "new"

        stopped = await mgr.stop_task_for_session("test:c1", "a1")
        assert stopped is True
        assert mgr.get_task_status_for_session("test:c1", "a1") == "cancelled"

    @pytest.mark.asyncio
    async def test_subagent_preserves_reasoning_fields_in_tool_turn(self, monkeypatch, tmp_path):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        captured_second_call: list[dict] = []

        call_count = {"n": 0}

        async def scripted_chat_with_retry(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return LLMResponse(
                    content="thinking",
                    tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={})],
                    reasoning_content="hidden reasoning",
                    thinking_blocks=[{"type": "thinking", "thinking": "step"}],
                )
            captured_second_call[:] = messages
            return LLMResponse(content="done", tool_calls=[])
        provider.chat_with_retry = scripted_chat_with_retry
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        async def fake_execute(self, name, arguments):
            return "tool result"

        monkeypatch.setattr("nanobot.agent.tools.registry.ToolRegistry.execute", fake_execute)

        await mgr._run_subagent("sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"})

        assistant_messages = [
            msg for msg in captured_second_call
            if msg.get("role") == "assistant" and msg.get("tool_calls")
        ]
        assert len(assistant_messages) == 1
        assert assistant_messages[0]["reasoning_content"] == "hidden reasoning"
        assert assistant_messages[0]["thinking_blocks"] == [{"type": "thinking", "thinking": "step"}]

    @pytest.mark.asyncio
    async def test_subagent_exec_tool_not_registered_when_disabled(self, tmp_path):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus
        from nanobot.config.schema import ExecToolConfig

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            provider=provider,
            workspace=tmp_path,
            bus=bus,
            exec_config=ExecToolConfig(enable=False),
        )
        mgr._announce_result = AsyncMock()

        async def fake_run(spec):
            assert spec.tools.get("exec") is None
            return SimpleNamespace(
                stop_reason="done",
                final_content="done",
                error=None,
                tool_events=[],
            )

        mgr.runner.run = AsyncMock(side_effect=fake_run)

        await mgr._run_subagent("sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"})

        mgr.runner.run.assert_awaited_once()
        mgr._announce_result.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subagent_announces_error_when_tool_execution_fails(self, monkeypatch, tmp_path):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="thinking",
            tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={})],
        ))
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)
        mgr._announce_result = AsyncMock()

        calls = {"n": 0}

        async def fake_execute(self, name, arguments):
            calls["n"] += 1
            if calls["n"] == 1:
                return "first result"
            raise RuntimeError("boom")

        monkeypatch.setattr("nanobot.agent.tools.registry.ToolRegistry.execute", fake_execute)

        await mgr._run_subagent("sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"})

        mgr._announce_result.assert_awaited_once()
        args = mgr._announce_result.await_args.args
        assert "Completed steps:" in args[3]
        assert "- list_dir: first result" in args[3]
        assert "Failure:" in args[3]
        assert "- list_dir: boom" in args[3]
        assert args[5] == "error"

    @pytest.mark.asyncio
    async def test_cancel_by_session_cancels_running_subagent_tool(self, monkeypatch, tmp_path):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="thinking",
            tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={})],
        ))
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)
        mgr._announce_result = AsyncMock()

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fake_execute(self, name, arguments):
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        monkeypatch.setattr("nanobot.agent.tools.registry.ToolRegistry.execute", fake_execute)

        task = asyncio.create_task(
            mgr._run_subagent("sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"})
        )
        mgr._running_tasks["sub-1"] = task
        mgr._session_tasks["test:c1"] = {"sub-1"}

        await started.wait()

        count = await mgr.cancel_by_session("test:c1")

        assert count == 1
        assert cancelled.is_set()
        assert task.cancelled()
        mgr._announce_result.assert_not_awaited()
