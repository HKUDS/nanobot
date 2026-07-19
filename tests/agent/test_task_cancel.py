"""Tests for /stop task cancellation."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import GenerationSettings
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.utils.llm_runtime import LLMRuntime

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def _runtime(provider: MagicMock | None = None) -> LLMRuntime:
    provider = provider or MagicMock()
    provider.generation = GenerationSettings()
    return LLMRuntime.capture(provider, "test-model", context_window_tokens=128_000)


def _make_loop(*, tools_config=None):
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
         patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr:
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace, tools_config=tools_config)
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
    @pytest.mark.asyncio
    async def test_run_logs_and_continues_after_leaked_cancelled_error(self, monkeypatch):
        loop, bus = _make_loop()
        loop._connect_mcp = AsyncMock()
        loop.close_mcp = AsyncMock()
        loop.auto_compact.check_expired = MagicMock()
        warnings: list[str] = []
        calls = 0

        async def consume_once_then_stop():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise asyncio.CancelledError()
            loop.stop()
            raise asyncio.TimeoutError()

        monkeypatch.setattr(bus, "consume_inbound", consume_once_then_stop)
        monkeypatch.setattr(
            "nanobot.agent.loop.logger.warning",
            lambda message, *args, **kwargs: warnings.append(message),
        )

        await loop.run()

        assert calls == 2
        assert any("Ignoring leaked CancelledError" in warning for warning in warnings)

    def test_exec_tool_not_registered_when_disabled(self):
        from nanobot.agent.tools.shell import ExecToolConfig
        from nanobot.config.schema import ToolsConfig

        loop, _bus = _make_loop(tools_config=ToolsConfig(exec=ExecToolConfig(enable=False)))

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
    async def test_dispatch_streaming_preserves_message_metadata(self):
        from nanobot.bus.events import InboundMessage
        from nanobot.bus.outbound_events import StreamDeltaEvent, StreamEndEvent

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
        assert isinstance(first.event, StreamDeltaEvent)
        assert second.metadata["thread_root_event_id"] == "$root1"
        assert second.metadata["thread_reply_to_event_id"] == "$reply1"
        assert isinstance(second.event, StreamEndEvent)

    @pytest.mark.asyncio
    async def test_processing_lock_serializes(self):
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        order = []
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def mock_process(m, **kwargs):
            order.append(f"start-{m.content}")
            if m.content == "a":
                first_started.set()
                await release_first.wait()
            order.append(f"end-{m.content}")
            return OutboundMessage(channel="test", chat_id="c1", content=m.content)

        loop._process_message = mock_process
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="a")
        msg2 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="b")

        t1 = asyncio.create_task(loop._dispatch(msg1))
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        t2 = asyncio.create_task(loop._dispatch(msg2))
        await asyncio.sleep(0)
        assert order == ["start-a"]

        release_first.set()
        await asyncio.gather(t1, t2)
        assert order == ["start-a", "end-a", "start-b", "end-b"]


class TestSubagentCancellation:
    @pytest.mark.asyncio
    async def test_cancel_by_session(self):
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        mgr = SubagentManager(
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

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
        mgr = SubagentManager(
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        assert await mgr.cancel_by_session("nonexistent") == 0

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
                    tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
                    reasoning_content="hidden reasoning",
                    thinking_blocks=[{"type": "thinking", "thinking": "step"}],
                )
            captured_second_call[:] = messages
            return LLMResponse(content="done", tool_calls=[])
        provider.chat_with_retry = scripted_chat_with_retry
        mgr = SubagentManager(
            workspace=tmp_path,
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )

        async def fake_execute(self, **kwargs):
            return "tool result"

        monkeypatch.setattr("nanobot.agent.tools.filesystem.ListDirTool.execute", fake_execute)

        from nanobot.agent.subagent import SubagentStatus
        status = SubagentStatus(task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic())
        await mgr._run_subagent(
            "sub-1",
            "do task",
            "label",
            {"channel": "test", "chat_id": "c1"},
            status,
            _runtime(provider),
        )

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
        from nanobot.agent.tools.shell import ExecToolConfig
        from nanobot.bus.queue import MessageBus
        from nanobot.config.schema import ToolsConfig

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(
            workspace=tmp_path,
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
            tools_config=ToolsConfig(exec=ExecToolConfig(enable=False)),
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

        from nanobot.agent.subagent import SubagentStatus
        status = SubagentStatus(task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic())
        await mgr._run_subagent(
            "sub-1",
            "do task",
            "label",
            {"channel": "test", "chat_id": "c1"},
            status,
            _runtime(provider),
        )

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
            tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
        ))
        mgr = SubagentManager(
            workspace=tmp_path,
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        mgr._announce_result = AsyncMock()

        calls = {"n": 0}

        async def fake_execute(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return "first result"
            raise RuntimeError("boom")

        monkeypatch.setattr("nanobot.agent.tools.filesystem.ListDirTool.execute", fake_execute)

        from nanobot.agent.subagent import SubagentStatus
        status = SubagentStatus(task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic())
        await mgr._run_subagent(
            "sub-1",
            "do task",
            "label",
            {"channel": "test", "chat_id": "c1"},
            status,
            _runtime(provider),
        )

        mgr._announce_result.assert_awaited_once()
        args = mgr._announce_result.await_args.args
        assert "Completed steps:" in args[3]
        assert "- list_dir: first result" in args[3]
        assert "Failure:" in args[3]
        assert "- list_dir: boom" in args[3]
        assert args[5] == "error"

    @pytest.mark.asyncio
    async def test_cancel_by_session_cancels_running_subagent_tool(self, monkeypatch, tmp_path):
        from nanobot.agent.subagent import SubagentManager, SubagentStatus
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
            content="thinking",
            tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})],
        ))
        mgr = SubagentManager(
            workspace=tmp_path,
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        mgr._announce_result = AsyncMock()

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fake_execute(self, **kwargs):
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        monkeypatch.setattr("nanobot.agent.tools.filesystem.ListDirTool.execute", fake_execute)

        task = asyncio.create_task(
            mgr._run_subagent(
                "sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"},
                SubagentStatus(task_id="sub-1", label="label", task_description="do task", started_at=time.monotonic()),
                _runtime(provider),
            )
        )
        mgr._running_tasks["sub-1"] = task
        mgr._session_tasks["test:c1"] = {"sub-1"}

        await asyncio.wait_for(started.wait(), timeout=1.0)

        count = await mgr.cancel_by_session("test:c1")

        assert count == 1
        assert cancelled.is_set()
        assert task.cancelled()
        mgr._announce_result.assert_not_awaited()


class TestSubagentAnnounceSessionKey:
    """Verify _announce_result uses the effective session key for mid-turn routing."""

    def _make_mgr(self):
        """Create a SubagentManager with mocked deps and its bus."""
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        mgr = SubagentManager(
            workspace=MagicMock(),
            bus=bus,
            max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
        )
        return mgr, bus

    @pytest.mark.asyncio
    async def test_announce_uses_effective_key_in_unified_mode(self):
        """In unified session mode, session_key_override must be 'unified:default'
        so the result matches the pending queue key."""
        mgr, bus = self._make_mgr()

        origin = {"channel": "telegram", "chat_id": "111", "session_key": UNIFIED_SESSION_KEY}
        await mgr._announce_result("sub-1", "label", "task", "result", origin, "ok")

        msg = await bus.consume_inbound()
        assert msg.session_key_override == UNIFIED_SESSION_KEY
        assert msg.session_key == UNIFIED_SESSION_KEY

    @pytest.mark.asyncio
    async def test_announce_uses_raw_key_in_normal_mode(self):
        """Without unified sessions, session_key_override is the raw channel:chat_id."""
        mgr, bus = self._make_mgr()

        origin = {"channel": "telegram", "chat_id": "222", "session_key": "telegram:222"}
        await mgr._announce_result("sub-2", "label", "task", "result", origin, "ok")

        msg = await bus.consume_inbound()
        assert msg.session_key_override == "telegram:222"
        assert msg.session_key == "telegram:222"

    @pytest.mark.asyncio
    async def test_announce_falls_back_to_origin_when_no_session_key(self):
        """When session_key is None, fallback to f'{channel}:{chat_id}'."""
        mgr, bus = self._make_mgr()

        origin = {"channel": "discord", "chat_id": "333", "session_key": None}
        await mgr._announce_result("sub-3", "label", "task", "result", origin, "ok")

        msg = await bus.consume_inbound()
        assert msg.session_key_override == "discord:333"
        assert msg.channel == "system"
        assert msg.chat_id == "discord:333"

    @pytest.mark.asyncio
    async def test_session_key_flows_through_run_subagent(self):
        """Verify session_key in origin propagates from _run_subagent to _announce_result."""
        from nanobot.agent.subagent import SubagentStatus

        mgr, bus = self._make_mgr()

        async def fake_run(spec):
            return SimpleNamespace(
                stop_reason="done",
                final_content="done",
                error=None,
                tool_events=[],
            )

        mgr.runner.run = AsyncMock(side_effect=fake_run)

        status = SubagentStatus(
            task_id="sub-4", label="label", task_description="task",
            started_at=time.monotonic(),
        )
        await mgr._run_subagent(
            "sub-4", "task", "label",
            {"channel": "telegram", "chat_id": "444", "session_key": UNIFIED_SESSION_KEY},
            status,
            _runtime(),
        )

        msg = await bus.consume_inbound()
        assert msg.session_key_override == UNIFIED_SESSION_KEY
