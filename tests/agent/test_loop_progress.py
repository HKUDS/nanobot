"""Tests for structured tool-event progress metadata emitted by AgentLoop."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


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

        # Drain all outbound messages and find the one carrying _tool_events
        outbound = []
        while bus.outbound_size > 0:
            outbound.append(await bus.consume_outbound())

        tool_event_msgs = [m for m in outbound if m.metadata and m.metadata.get("_tool_events")]
        assert tool_event_msgs, "expected at least one outbound message with _tool_events"

        start_msgs = [m for m in tool_event_msgs if m.metadata["_tool_events"][0]["phase"] == "start"]
        finish_msgs = [m for m in tool_event_msgs if m.metadata["_tool_events"][0]["phase"] in ("end", "error")]
        assert start_msgs, "expected a start-phase tool event"
        assert finish_msgs, "expected a finish-phase tool event"

        start = start_msgs[0].metadata["_tool_events"][0]
        assert start["name"] == "exec"
        assert start["call_id"] == "tc1"
        assert start["result"] is None

        finish = finish_msgs[0].metadata["_tool_events"][0]
        assert finish["phase"] == "end"
        assert finish["result"] == "file.txt"

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
        assert not any(m.metadata.get("_progress") for m in outbound)
        assert not any(m.metadata.get("_streamed") for m in outbound)
        provider.chat_stream_with_retry.assert_not_awaited()
        provider.chat_with_retry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_streaming_channel_streams_provider_deltas_for_codex_style_provider(
        self,
        tmp_path: Path,
    ) -> None:
        """Streaming channels still receive provider deltas through _stream_delta messages."""
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

        deltas = [m for m in outbound if m.metadata.get("_stream_delta")]
        stream_end = [m for m in outbound if m.metadata.get("_stream_end")]
        final = [
            m for m in outbound
            if not m.metadata.get("_stream_delta")
            and not m.metadata.get("_stream_end")
            and not m.metadata.get("_turn_end")
        ]

        assert [m.content for m in deltas] == ["Hel", "lo"]
        assert len(stream_end) == 1
        assert final[-1].content == "Hello"
        assert final[-1].metadata.get("_streamed") is True
        assert outbound[-1].metadata.get("_turn_end") is True
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

        assert outbound[-2].content == "Done"
        assert (outbound[-2].metadata or {}).get("_turn_end") is not True
        assert outbound[-1].content == ""
        assert (outbound[-1].metadata or {}).get("_turn_end") is True
        assert outbound[-1].chat_id == "chat1"

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
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock(return_value=False)  # type: ignore[method-assign]

        await asyncio.wait_for(loop._dispatch(InboundMessage(
            channel="websocket",
            sender_id="u1",
            chat_id="chat1",
            content="say hello",
            metadata={"webui": True},
        )), timeout=0.5)

        outbound = [await bus.consume_outbound(), await bus.consume_outbound()]
        assert outbound[0].content == "Done"
        assert (outbound[1].metadata or {}).get("_turn_end") is True

        await asyncio.wait_for(title_started.wait(), timeout=0.5)
        release_title.set()
        session_updated = await asyncio.wait_for(bus.consume_outbound(), timeout=0.5)

        assert (session_updated.metadata or {}).get("_session_updated") is True
        assert provider.chat_with_retry.await_count == 2

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
        assert (outbound[0].metadata or {}).get("_turn_end") is not True
