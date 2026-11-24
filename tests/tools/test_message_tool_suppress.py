import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.context import TranscriptInput
from nanobot.agent.hook import SDKCaptureHook
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import INBOUND_META_TURN_ID, InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import EmptyFinalResponseNotice, TurnEndEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import TurnCompleted
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.sdk.types import result_from_response
from nanobot.utils.progress_events import output_events


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


class TestMessageToolSuppressLogic:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ephemeral, max_iterations", [(False, 2), (True, 2), (False, 1)])
    async def test_suppress_when_sent_to_same_target(
        self,
        tmp_path: Path,
        ephemeral: bool,
        max_iterations: int,
    ) -> None:
        loop = _make_loop(tmp_path)
        loop.max_iterations = max_iterations
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Hello", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send")
        capture = SDKCaptureHook()
        result = await loop._process_message(
            msg, ephemeral=ephemeral, hooks=[capture], run_extra_hooks_for_ephemeral=True,
        )

        assert capture.stop_reason == "completed"
        assert len(sent) == 1
        assert result is None
        assert loop.provider.chat_stream_with_retry.await_count == max_iterations
        if not ephemeral:
            session = await loop.sessions.state.read(msg.session_key)
            assert session is not None
            assert not session.metadata.get("_stopped_at_iteration_limit")
            assert all(m.get("role") != "assistant" or m.get("tool_calls") or m.get("content") == "Done" for m in session.messages)

    @pytest.mark.asyncio
    async def test_not_suppress_when_sent_to_different_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Email content", "channel": "email", "chat_id": "user@example.com"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="I've sent the email.", tool_calls=[]),
        ])
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send email")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert sent[0].channel == "email"
        assert result is not None
        assert result.channel == "feishu"

    @pytest.mark.asyncio
    async def test_not_suppress_when_no_message_tool_used(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Hello!", tool_calls=[]))
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Hello" in result.content

    @pytest.mark.asyncio
    async def test_internal_message_check_keeps_final_response(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "all clear", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Heartbeat summary", tool_calls=[]),
        ])
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        mt = loop.tools.get("message")
        assert isinstance(mt, MessageTool)
        token = mt.set_suppress_delivery(True)
        try:
            msg = InboundMessage(
                channel="feishu", sender_id="user1", chat_id="chat123", content="Check",
            )
            result = await loop._process_message(msg)
        finally:
            mt.reset_suppress_delivery(token)

        assert result is not None
        assert result.content == "Heartbeat summary"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("final_text", ["", "Sent."])
    async def test_send_after_followup_completes_that_input_without_a_duplicate(
        self, tmp_path: Path, final_text: str,
    ) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Tool reply", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter([
            LLMResponse(content="First answer", tool_calls=[]),
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content=final_text),
        ])
        pending_queue: asyncio.Queue[InboundMessage] = asyncio.Queue()

        async def next_response(*_args, **_kwargs):
            response = next(calls)
            if response.content == "First answer":
                pending_queue.put_nowait(InboundMessage(
                    channel="feishu",
                    sender_id="user1",
                    chat_id="chat123",
                    content="follow-up",
                    metadata={INBOUND_META_TURN_ID: "follow-up"},
                ))
            return response

        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=next_response)
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Start")
        completed: list[TurnCompleted] = []
        loop.bus.subscribe(completed.append, TurnCompleted)
        delivery = loop.turn_delivery_factory.create(msg, msg.session_key)
        capture = SDKCaptureHook()
        capture.on_error = AsyncMock()
        result = await loop._process_message(msg, pending_queue=pending_queue, delivery=delivery, hooks=[capture])
        await delivery.complete(result, publish_completion=True)

        assert len(sent) == 1
        assert sent[0].content == "Tool reply"
        assert sent[0].metadata["response_input_ids"] == ["user:follow-up"]
        assert result is None
        assert [event.outcome for event in completed] == ["completed"]
        sdk = result_from_response(result, capture)
        assert (sdk.stop_reason, sdk.error, sdk.tools_used) == ("completed", None, ["message"])
        capture.on_error.assert_not_awaited()

    @pytest.mark.parametrize("final_text", ["", "New answer"])
    async def test_send_before_followup_does_not_answer_the_new_input(self, tmp_path: Path, final_text: str) -> None:
        loop = _make_loop(tmp_path)
        pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
        msg = InboundMessage(channel="feishu", sender_id="user", chat_id="chat", content="Start")

        async def on_send(_message: OutboundMessage) -> None:
            # Even inputs without public IDs have separate reply ownership.
            pending.put_nowait(InboundMessage(channel="feishu", sender_id="user", chat_id="chat", content="Next?"))

        tool = loop.tools.get("message")
        assert isinstance(tool, MessageTool)
        tool.set_send_callback(on_send)
        call = ToolCallRequest(id="send", name="message", arguments={"content": "First answer"})
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
            LLMResponse(tool_calls=[call], content=None),
            *[LLMResponse(content=final_text) for _ in range(1 if final_text else 3)],
        ])
        capture = SDKCaptureHook()
        capture.on_error = AsyncMock()
        result = await loop._process_message(msg, pending_queue=pending, hooks=[capture])

        assert result is not None
        sdk = result_from_response(result, capture)
        if final_text:
            assert (sdk.content, sdk.stop_reason, sdk.error) == (final_text, "completed", None)
            capture.on_error.assert_not_awaited()
        else:
            assert (sdk.content, sdk.stop_reason, sdk.error) == ("", "empty_final_response", "empty_final_response")
            capture.on_error.assert_awaited_once()

    @pytest.mark.parametrize("channel", ["websocket", "feishu"])
    async def test_undelivered_empty_final_reaches_channel_as_failure(self, tmp_path: Path, channel: str) -> None:
        loop = _make_loop(tmp_path)
        from nanobot.session.webui_turns import WebuiTurnCoordinator

        loop.provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="", finish_reason="length"))
        msg = InboundMessage(channel=channel, sender_id="user", chat_id="chat", content="Start")
        completed: list[TurnCompleted] = []
        loop.bus.subscribe(completed.append, TurnCompleted)
        delivery = loop.turn_delivery_factory.create(msg, msg.session_key)
        with WebuiTurnCoordinator(loop.bus, loop.sessions, loop.schedule_background).connected():
            result = await loop._process_message(msg, delivery=delivery)
            await delivery.complete(result, publish_completion=True)

        assert result is not None and result.content == ""
        assert result.event == EmptyFinalResponseNotice(output_limited=True)
        assert [(e.outcome, e.failure_kind, e.failure_error_kind) for e in completed] == [
            ("failed", "model", "empty_final_response_length"),
        ]
        # The WebSocket coordinator projects the lifecycle completion; other channels get the routed event.
        routed = [loop.bus.outbound.get_nowait() for _ in range(loop.bus.outbound_size)]
        terminal = [m.event for m in routed if isinstance(m.event, EmptyFinalResponseNotice | TurnEndEvent)]
        if channel == "websocket":
            [end] = terminal
            assert isinstance(end, TurnEndEvent)
            assert (end.outcome, end.failure_error_kind, end.failure_message) == ("failed", "empty_final_response_length", None)
        else:
            assert terminal == [result.event]

    async def test_progress_hides_internal_reasoning(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(
                content="Visible<think>hidden</think>",
                tool_calls=[tool_call],
                reasoning_content="secret reasoning",
                thinking_blocks=[{"signature": "sig", "thought": "secret thought"}],
            ),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[tuple[str, bool]] = []

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            progress.append((content, tool_hint))

        result = await loop._run_agent_loop(
            TranscriptInput(history=[], current_message=None),
            runtime=loop.llm_runtime(),
            events=output_events(on_progress=on_progress),
        )

        assert result.final_content == "Done"
        assert progress == [
            ("Visible", False),
            ("", True),
        ]

class TestMessageToolSchema:

    def test_schema_discourages_current_chat_replies(self) -> None:
        tool = MessageTool()

        assert "For normal replies, including scheduled reminders and reports, answer directly" in tool.description
        assert "the final reply is delivered to the current chat automatically" in tool.description
        assert "deliver generated images via media" in tool.description
        assert (
            "Use artifact paths returned by generate_image"
            in tool.parameters["properties"]["media"]["description"]
        )
