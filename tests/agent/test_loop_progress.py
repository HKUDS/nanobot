"""Tests for structured tool-event progress metadata emitted by AgentLoop."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.hooks import create_file_edit_activity_hook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.filesystem import WriteFileTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import (
    GoalStatusEvent,
    ProgressEvent,
    SessionUpdatedEvent,
    StreamDeltaEvent,
    StreamedResponseEvent,
    StreamEndEvent,
    TurnEndEvent,
)
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.session.webui_turns import WebuiTurnCoordinator
from nanobot.utils.progress_events import (
    invoke_file_edit_progress,
    on_progress_accepts_file_edit_events,
)


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        hook_factories=[create_file_edit_activity_hook],
    )


def _attach_webui_runtime_events(loop: AgentLoop, bus: MessageBus) -> None:
    coordinator = WebuiTurnCoordinator(
        bus=bus,
        sessions=loop.sessions,
        schedule_background=lambda coro: loop._schedule_background(coro),
    )
    coordinator.subscribe(loop.runtime_events)


class TestToolEventProgress:
    """_run_agent_loop emits structured tool_events via on_progress."""

    @pytest.mark.asyncio
    async def test_start_and_finish_events_emitted(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="custom_tool", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="Visible", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.prepare_call = MagicMock(return_value=(None, {"path": "foo.txt"}, None))
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[tuple[str, bool, list[dict] | None]] = []

        async def on_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict] | None = None,
        ) -> None:
            progress.append((content, tool_hint, tool_events))

        final_content, _, _, _, _ = await loop._run_agent_loop([], on_progress=on_progress)

        assert final_content == "Done"
        assert progress == [
            ("Visible", False, None),
            (
                'custom_tool("foo.txt")',
                True,
                [{
                    "version": 1,
                    "phase": "start",
                    "call_id": "call1",
                    "name": "custom_tool",
                    "arguments": {"path": "foo.txt"},
                    "result": None,
                    "error": None,
                    "files": [],
                    "embeds": [],
                }],
            ),
            (
                "",
                False,
                [{
                    "version": 1,
                    "phase": "end",
                    "call_id": "call1",
                    "name": "custom_tool",
                    "arguments": {"path": "foo.txt"},
                    "result": "ok",
                    "error": None,
                    "files": [],
                    "embeds": [],
                }],
            ),
        ]

    @pytest.mark.asyncio
    async def test_write_file_emits_file_edit_progress(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        target = tmp_path / "foo.txt"
        target.write_text("old\n", encoding="utf-8")
        tool_call = ToolCallRequest(
            id="call-write",
            name="write_file",
            arguments={"path": "foo.txt", "content": "new\nextra\n"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        tool = WriteFileTool(workspace=tmp_path)
        loop.tools.prepare_call = MagicMock(
            return_value=(tool, {"path": "foo.txt", "content": "new\nextra\n"}, None),
        )
        file_events: list[dict] = []

        async def on_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict] | None = None,
            file_edit_events: list[dict] | None = None,
        ) -> None:
            if file_edit_events:
                file_events.extend(file_edit_events)

        final_content, _, _, _, _ = await loop._run_agent_loop([], on_progress=on_progress)

        assert final_content == "Done"
        assert [event["phase"] for event in file_events] == ["start", "end"]
        assert file_events[0] == {
            "version": 1,
            "call_id": "call-write",
            "tool": "write_file",
            "path": "foo.txt",
            "absolute_path": (tmp_path / "foo.txt").resolve().as_posix(),
            "phase": "start",
            "added": 0,
            "deleted": 0,
            "approximate": True,
            "status": "editing",
        }
        assert file_events[1]["status"] == "done"
        assert file_events[1]["approximate"] is False
        assert (file_events[1]["added"], file_events[1]["deleted"]) == (2, 1)
        assert file_events[1]["diff"]["format"] == "unified"

    @pytest.mark.asyncio
    async def test_file_edit_snapshot_skipped_when_progress_callback_cannot_emit_file_edits(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        loop = _make_loop(tmp_path)
        target = tmp_path / "foo.txt"
        target.write_text("old\n", encoding="utf-8")
        prepare_file_edit_trackers = MagicMock()

        class ObservableWriteTool:
            name = "write_file"

            async def execute(self, path: str, content: str) -> str:
                target.write_text(content, encoding="utf-8")
                return "ok"

        tool = ObservableWriteTool()
        tool_call = ToolCallRequest(
            id="call-write",
            name="write_file",
            arguments={"path": "foo.txt", "content": "new\n"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.prepare_call = MagicMock(
            return_value=(tool, {"path": "foo.txt", "content": "new\n"}, None),
        )

        async def on_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict] | None = None,
        ) -> None:
            pass

        monkeypatch.setattr(
            "nanobot.agent.hooks.file_edit_activity.prepare_file_edit_trackers",
            prepare_file_edit_trackers,
        )

        final_content, _, _, _, _ = await loop._run_agent_loop([], on_progress=on_progress)

        assert final_content == "Done"
        assert target.read_text(encoding="utf-8") == "new\n"
        prepare_file_edit_trackers.assert_not_called()

    @pytest.mark.asyncio
    async def test_exec_does_not_emit_file_edit_progress(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call-exec",
            name="exec",
            arguments={"command": "printf hi > foo.txt"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.prepare_call = MagicMock(
            return_value=(None, {"command": "printf hi > foo.txt"}, None),
        )
        loop.tools.execute = AsyncMock(return_value="ok")
        file_events: list[dict] = []

        async def on_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict] | None = None,
            file_edit_events: list[dict] | None = None,
        ) -> None:
            if file_edit_events:
                file_events.extend(file_edit_events)

        await loop._run_agent_loop([], on_progress=on_progress)

        assert file_events == []

    @pytest.mark.asyncio
    async def test_bus_progress_forwards_tool_events_to_outbound_metadata(self, tmp_path: Path) -> None:
        """When run() handles a bus message, _tool_events lands in OutboundMessage metadata."""
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

        tool_call = ToolCallRequest(id="tc1", name="exec", arguments={"command": "ls"})
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.prepare_call = MagicMock(return_value=(None, {"command": "ls"}, None))
        loop.tools.execute = AsyncMock(return_value="file.txt")

        msg = InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat1",
            content="run ls",
        )
        await loop._dispatch(msg)

        # Drain all outbound messages and find the one carrying tool events.
        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        tool_event_msgs = [
            m
            for m in outbound
            if isinstance(m.event, ProgressEvent) and m.event.tool_events
        ]
        assert tool_event_msgs, "expected at least one outbound message with tool events"

        start_msgs = [
            m
            for m in tool_event_msgs
            if isinstance(m.event, ProgressEvent)
            and m.event.tool_events
            and m.event.tool_events[0]["phase"] == "start"
        ]
        finish_msgs = [
            m
            for m in tool_event_msgs
            if isinstance(m.event, ProgressEvent)
            and m.event.tool_events
            and m.event.tool_events[0]["phase"] in ("end", "error")
        ]
        assert start_msgs, "expected a start-phase tool event"
        assert finish_msgs, "expected a finish-phase tool event"

        assert isinstance(start_msgs[0].event, ProgressEvent)
        assert start_msgs[0].event.tool_events is not None
        start = start_msgs[0].event.tool_events[0]
        assert start["name"] == "exec"
        assert start["call_id"] == "tc1"
        assert start["result"] is None

        assert isinstance(finish_msgs[0].event, ProgressEvent)
        assert finish_msgs[0].event.tool_events is not None
        finish = finish_msgs[0].event.tool_events[0]
        assert finish["phase"] == "end"
        assert finish["result"] == "file.txt"

    @pytest.mark.asyncio
    async def test_bus_progress_forwards_file_edit_events_without_channel_branch(self, tmp_path: Path) -> None:
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
        edit_events = [{
            "call_id": "call-write",
            "tool": "write_file",
            "path": "foo.txt",
            "phase": "start",
            "added": 1,
            "deleted": 0,
            "approximate": True,
            "status": "editing",
        }]

        progress = await loop._build_bus_progress_callback(InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="chat1",
            content="edit",
        ))
        assert on_progress_accepts_file_edit_events(progress) is True
        await invoke_file_edit_progress(progress, edit_events)
        outbound = await bus.consume_outbound()
        assert outbound.channel == "telegram"
        assert isinstance(outbound.event, ProgressEvent)
        assert outbound.event.file_edit_events == edit_events

    @pytest.mark.asyncio
    async def test_goal_turn_keeps_file_edit_progress_for_webui(self, tmp_path: Path) -> None:
        """The /goal command rewrites the prompt but must not bypass WebUI file-edit progress."""
        bus = MessageBus()
        provider = MagicMock()
        provider.supports_progress_deltas = True
        provider.get_default_model.return_value = "test-model"
        call_count = 0

        async def chat_stream_with_retry(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id="call-goal-write",
                            name="write_file",
                            arguments={
                                "path": "goal.txt",
                                "content": "one\ntwo\nthree\n",
                            },
                        )
                    ],
                    usage={},
                )
            return LLMResponse(content="Done", tool_calls=[], usage={})

        provider.chat_stream_with_retry = chat_stream_with_retry
        provider.chat_with_retry = AsyncMock()
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            hook_factories=[create_file_edit_activity_hook],
        )
        tool = WriteFileTool(workspace=tmp_path)
        loop.tools.get_definitions = MagicMock(return_value=[
            {"type": "function", "function": {"name": "write_file"}},
        ])
        loop.tools.prepare_call = MagicMock(
            return_value=(
                tool,
                {"path": "goal.txt", "content": "one\ntwo\nthree\n"},
                None,
            ),
        )
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="/goal create goal file",
            metadata={"_wants_stream": True},
        ))

        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        edit_events = [
            event
            for msg in outbound
            if isinstance(msg.event, ProgressEvent)
            for event in msg.event.file_edit_events or []
        ]
        assert any(
            event["status"] == "editing"
            and event["approximate"]
            and event["added"] == 0
            for event in edit_events
        )
        assert any(
            event["status"] == "done"
            and not event["approximate"]
            and event["added"] == 3
            and event.get("diff", {}).get("format") == "unified"
            for event in edit_events
        )
        provider.chat_with_retry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_streaming_channel_does_not_publish_codex_progress_deltas(
        self,
        tmp_path: Path,
    ) -> None:
        """Non-streaming channels should get one final reply, not token progress spam."""
        bus = MessageBus()
        provider = MagicMock()
        provider.supports_progress_deltas = True
        provider.get_default_model.return_value = "openai-codex/gpt-5.5"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Hello", tool_calls=[]))
        provider.chat_stream_with_retry = AsyncMock()
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="openai-codex/gpt-5.5")
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="whatsapp",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
        ))

        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        assert [m.content for m in outbound] == ["Hello"]
        assert not any(isinstance(m.event, ProgressEvent) for m in outbound)
        assert not any(isinstance(m.event, StreamedResponseEvent) for m in outbound)
        provider.chat_stream_with_retry.assert_not_awaited()
        provider.chat_with_retry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_streaming_channel_streams_provider_deltas_for_codex_style_provider(
        self,
        tmp_path: Path,
    ) -> None:
        """Streaming channels still receive provider deltas through stream events."""
        bus = MessageBus()
        provider = MagicMock()
        provider.supports_progress_deltas = True
        provider.get_default_model.return_value = "openai-codex/gpt-5.5"

        async def chat_stream_with_retry(*, on_content_delta, **kwargs):
            await on_content_delta("Hel")
            await on_content_delta("lo")
            return LLMResponse(content="Hello", tool_calls=[])

        provider.chat_stream_with_retry = chat_stream_with_retry
        provider.chat_with_retry = AsyncMock()
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="openai-codex/gpt-5.5")
        _attach_webui_runtime_events(loop, bus)
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
            metadata={"_wants_stream": True},
        ))

        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        deltas = [m for m in outbound if isinstance(m.event, StreamDeltaEvent)]
        stream_end = [m for m in outbound if isinstance(m.event, StreamEndEvent)]
        final = [
            m for m in outbound
            if not isinstance(m.event, StreamDeltaEvent | StreamEndEvent)
            and not isinstance(m.event, TurnEndEvent | GoalStatusEvent)
        ]

        assert [m.content for m in deltas] == ["Hel", "lo"]
        assert len(stream_end) == 1
        assert final[-1].content == "Hello"
        assert isinstance(final[-1].event, StreamedResponseEvent)
        turn_end_msgs = [m for m in outbound if isinstance(m.event, TurnEndEvent)]
        assert len(turn_end_msgs) == 1
        assert turn_end_msgs[0].content == ""
        provider.chat_with_retry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stream_timeout_recovery_continues_in_new_segment(
        self,
        tmp_path: Path,
    ) -> None:
        """Recovered streaming output should use a new stream segment."""
        bus = MessageBus()
        provider = MagicMock()
        provider.supports_progress_deltas = True
        provider.get_default_model.return_value = "openai-codex/gpt-5.5"

        async def chat_stream_with_retry(*, on_content_delta, on_stream_recover, **kwargs):
            await on_content_delta("partial")
            await on_stream_recover()
            await on_content_delta("full retry response")
            return LLMResponse(content="full retry response", tool_calls=[])

        provider.chat_stream_with_retry = chat_stream_with_retry
        provider.chat_with_retry = AsyncMock()
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="openai-codex/gpt-5.5")
        _attach_webui_runtime_events(loop, bus)
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
            metadata={"_wants_stream": True},
        ))

        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        deltas = [m for m in outbound if isinstance(m.event, StreamDeltaEvent)]
        stream_end = [m for m in outbound if isinstance(m.event, StreamEndEvent)]
        final = [
            m for m in outbound
            if not isinstance(m.event, StreamDeltaEvent | StreamEndEvent)
            and not isinstance(m.event, TurnEndEvent | GoalStatusEvent)
        ]

        assert [m.content for m in deltas] == ["partial", "full retry response"]
        assert [m.event.resuming for m in stream_end if isinstance(m.event, StreamEndEvent)] == [
            True,
            False,
        ]
        assert isinstance(deltas[0].event, StreamDeltaEvent)
        assert isinstance(deltas[1].event, StreamDeltaEvent)
        assert isinstance(stream_end[0].event, StreamEndEvent)
        assert isinstance(stream_end[1].event, StreamEndEvent)
        assert deltas[0].event.stream_id == stream_end[0].event.stream_id
        assert deltas[1].event.stream_id == stream_end[1].event.stream_id
        assert deltas[0].event.stream_id != deltas[1].event.stream_id
        assert final[-1].content == "full retry response"
        assert isinstance(final[-1].event, StreamedResponseEvent)
        provider.chat_with_retry.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_streamed_progress_is_not_repeated_before_tool_execution(
        self,
        tmp_path: Path,
    ) -> None:
        """If content was already streamed as progress, tool setup should not repeat it."""
        loop = _make_loop(tmp_path)
        loop.provider.supports_progress_deltas = True
        tool_call = ToolCallRequest(id="call1", name="custom_tool", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="I will inspect it.", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])

        async def chat_stream_with_retry(*, on_content_delta, **kwargs):
            response = next(calls)
            if response.tool_calls:
                await on_content_delta("I will ")
                await on_content_delta("inspect it.")
            return response

        loop.provider.chat_stream_with_retry = chat_stream_with_retry
        loop.provider.chat_with_retry = AsyncMock()
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.prepare_call = MagicMock(return_value=(None, {"path": "foo.txt"}, None))
        loop.tools.execute = AsyncMock(return_value="ok")

        streamed: list[str] = []
        progress: list[tuple[str, bool, list[dict] | None]] = []

        async def on_stream(delta: str) -> None:
            streamed.append(delta)

        async def on_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict] | None = None,
        ) -> None:
            progress.append((content, tool_hint, tool_events))

        final_content, _, _, _, _ = await loop._run_agent_loop(
            [],
            on_progress=on_progress,
            on_stream=on_stream,
        )

        assert final_content == "Done"
        assert streamed == ["I will", " inspect it."]
        assert progress[0][0] == 'custom_tool("foo.txt")'
        assert all(item[0] != "I will inspect it." for item in progress)

    @pytest.mark.asyncio
    async def test_websocket_dispatch_publishes_final_turn_end_marker(self, tmp_path: Path) -> None:
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Done", tool_calls=[]))
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
        _attach_webui_runtime_events(loop, bus)
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
        ))

        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        done_msgs = [m for m in outbound if m.content == "Done"]
        assert len(done_msgs) == 1
        assert not isinstance(done_msgs[0].event, TurnEndEvent)

        turn_end_msgs = [m for m in outbound if isinstance(m.event, TurnEndEvent)]
        assert len(turn_end_msgs) == 1
        assert turn_end_msgs[0].content == ""
        assert turn_end_msgs[0].chat_id == "chat1"
        assert outbound.index(done_msgs[0]) < outbound.index(turn_end_msgs[0])

    @pytest.mark.asyncio
    async def test_websocket_dispatch_publishes_turn_end_after_error(
        self,
        tmp_path: Path,
    ) -> None:
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
        _attach_webui_runtime_events(loop, bus)

        async def raise_from_turn(*_args, **_kwargs):
            raise RuntimeError("boom")

        loop._process_message = raise_from_turn  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
        ))

        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        error_msgs = [m for m in outbound if m.content == "Sorry, I encountered an error."]
        turn_end_msgs = [m for m in outbound if isinstance(m.event, TurnEndEvent)]
        statuses = [m for m in outbound if isinstance(m.event, GoalStatusEvent)]

        assert len(error_msgs) == 1
        assert len(turn_end_msgs) == 1
        assert turn_end_msgs[0].content == ""
        assert turn_end_msgs[0].chat_id == "chat1"
        assert [m.event.status for m in statuses if isinstance(m.event, GoalStatusEvent)] == ["idle"]
        assert outbound.index(error_msgs[0]) < outbound.index(turn_end_msgs[0])
        assert outbound.index(turn_end_msgs[0]) < outbound.index(statuses[-1])

    @pytest.mark.asyncio
    async def test_webui_title_generation_runs_after_turn_end(self, tmp_path: Path) -> None:
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        title_started = asyncio.Event()
        release_title = asyncio.Event()
        calls = 0

        async def chat_with_retry(*_args: object, **_kwargs: object) -> LLMResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                return LLMResponse(content="Done", tool_calls=[])
            title_started.set()
            await release_title.wait()
            return LLMResponse(content="Generated title", tool_calls=[])

        provider.chat_with_retry = AsyncMock(side_effect=chat_with_retry)
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
        _attach_webui_runtime_events(loop, bus)
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        await asyncio.wait_for(loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
            metadata={"webui": True},
        )), timeout=0.5)

        outbound: list = []
        for _ in range(12):
            outbound.append(await asyncio.wait_for(bus.consume_outbound(), timeout=0.5))
            if isinstance(outbound[-1].event, TurnEndEvent):
                break
        else:
            raise AssertionError("turn-end event not found")

        done_with_body = [m for m in outbound if m.content == "Done"]
        assert len(done_with_body) == 1
        assert isinstance(outbound[-1].event, TurnEndEvent)

        await asyncio.wait_for(title_started.wait(), timeout=0.5)
        release_title.set()
        session_updated = None
        for _ in range(10):
            candidate = await asyncio.wait_for(bus.consume_outbound(), timeout=0.5)
            if isinstance(candidate.event, SessionUpdatedEvent):
                session_updated = candidate
                break
        assert session_updated is not None

        assert isinstance(session_updated.event, SessionUpdatedEvent)
        assert session_updated.event.scope == "metadata"
        assert provider.chat_with_retry.await_count == 2

    @pytest.mark.asyncio
    async def test_webui_title_generation_uses_turn_model_snapshot(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Done", tool_calls=[]))
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
        _attach_webui_runtime_events(loop, bus)
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        captured: dict[str, object] = {}

        async def fake_title_after_turn(**kwargs: object) -> bool:
            captured.update(kwargs)
            return False

        monkeypatch.setattr(
            "nanobot.session.webui_turns.maybe_generate_webui_title_after_turn",
            fake_title_after_turn,
        )
        scheduled_title: list[object] = []

        def schedule_background(coro: object) -> None:
            name = getattr(coro, "__qualname__", "")
            if "_generate_title_and_notify" in name:
                scheduled_title.append(coro)
            elif hasattr(coro, "close"):
                coro.close()

        loop._schedule_background = schedule_background  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
            metadata={"webui": True},
        ))

        assert len(scheduled_title) == 1
        loop.provider = MagicMock()
        loop.model = "switched-after-turn"

        await scheduled_title[0]  # type: ignore[misc]

        assert captured["provider"] is provider
        assert captured["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_webui_command_turn_does_not_schedule_title_generation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Done", tool_calls=[]))
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
        _attach_webui_runtime_events(loop, bus)

        async def fake_title_after_turn(**_kwargs: object) -> bool:
            raise AssertionError("command-only turns should not generate titles")

        monkeypatch.setattr(
            "nanobot.session.webui_turns.maybe_generate_webui_title_after_turn",
            fake_title_after_turn,
        )
        scheduled: list[object] = []
        loop._schedule_background = scheduled.append  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="/model",
            metadata={"webui": True},
        ))

        assert scheduled == []

    @pytest.mark.asyncio
    async def test_non_websocket_dispatch_does_not_publish_turn_end_marker(self, tmp_path: Path) -> None:
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Done", tool_calls=[]))
        loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        await loop._dispatch(InboundMessage(
            channel="slack",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
        ))

        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        assert len(outbound) == 1
        assert outbound[0].content == "Done"
        assert not isinstance(outbound[0].event, TurnEndEvent)
