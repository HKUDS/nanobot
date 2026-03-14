"""Test message tool suppress logic for final replies."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


class TestMessageToolSuppressLogic:
    """Final reply suppressed only when message tool sends to the same target."""

    @pytest.mark.asyncio
    async def test_suppress_when_sent_to_same_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1",
            name="message",
            arguments={"content": "Hello", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter(
            [
                LLMResponse(content="", tool_calls=[tool_call]),
                LLMResponse(content="Done", tool_calls=[]),
            ]
        )
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert result is None  # suppressed

    @pytest.mark.asyncio
    async def test_not_suppress_when_sent_to_different_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1",
            name="message",
            arguments={
                "content": "Email content",
                "channel": "email",
                "chat_id": "user@example.com",
            },
        )
        calls = iter(
            [
                LLMResponse(content="", tool_calls=[tool_call]),
                LLMResponse(content="I've sent the email.", tool_calls=[]),
            ]
        )
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(
            channel="feishu", sender_id="user1", chat_id="chat123", content="Send email"
        )
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert sent[0].channel == "email"
        assert result is not None  # not suppressed
        assert result.channel == "feishu"

    @pytest.mark.asyncio
    async def test_not_suppress_when_no_message_tool_used(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="Hello!", tool_calls=[])
        )
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Hello" in result.content

    @pytest.mark.asyncio
    async def test_retry_synthesis_when_empty_content_after_tool_calls(
        self, tmp_path: Path
    ) -> None:
        """Retry when LLM returns empty content after tool calls (fixes #235, #640).

        Sequence:
          1. tool call response
          2. empty content (no tool calls) — should trigger retry
          3. actual content — should become final_content
        """
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter(
            [
                LLMResponse(content="", tool_calls=[tool_call]),
                LLMResponse(content=None, tool_calls=[]),  # empty after tool → retry
                LLMResponse(content="Here is the result.", tool_calls=[]),
            ]
        )
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="file contents")

        final_content, tools_used, _ = await loop._run_agent_loop([])

        assert final_content == "Here is the result."
        assert tools_used == ["read_file"]

    @pytest.mark.asyncio
    async def test_retry_synthesis_capped_at_max_retries(self, tmp_path: Path) -> None:
        """After _MAX_SYNTHESIS_RETRIES consecutive empty responses, stop retrying.

        After the cap is hit the next empty response is treated as a normal (non-retry)
        empty reply: final_content=None is set and the loop breaks.
        """
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        # 1 tool call + 2 retried empties (hitting the cap) + 1 final empty (breaks loop)
        calls = iter(
            [
                LLMResponse(content="", tool_calls=[tool_call]),
                LLMResponse(content=None, tool_calls=[]),  # retry 1
                LLMResponse(content=None, tool_calls=[]),  # retry 2 (cap reached)
                LLMResponse(content=None, tool_calls=[]),  # cap exceeded → normal branch → break
            ]
        )
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="file contents")

        final_content, tools_used, _ = await loop._run_agent_loop([])

        # After 2 retries the loop exits with final_content=None (triggers fallback upstream)
        assert final_content is None
        # chat_with_retry called exactly 4 times: 1 tool call + 2 retries + 1 cap-exceeded break
        assert loop.provider.chat_with_retry.call_count == 4

    async def test_progress_hides_internal_reasoning(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter(
            [
                LLMResponse(
                    content="Visible<think>hidden</think>",
                    tool_calls=[tool_call],
                    reasoning_content="secret reasoning",
                    thinking_blocks=[{"signature": "sig", "thought": "secret thought"}],
                ),
                LLMResponse(content="Done", tool_calls=[]),
            ]
        )
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[tuple[str, bool]] = []

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            progress.append((content, tool_hint))

        final_content, _, _ = await loop._run_agent_loop([], on_progress=on_progress)

        assert final_content == "Done"
        assert progress == [
            ("Visible", False),
            ('read_file("foo.txt")', True),
        ]


class TestMessageToolTurnTracking:
    def test_sent_in_turn_tracks_same_target(self) -> None:
        tool = MessageTool()
        tool.set_context("feishu", "chat1")
        assert not tool._sent_in_turn
        tool._sent_in_turn = True
        assert tool._sent_in_turn

    def test_start_turn_resets(self) -> None:
        tool = MessageTool()
        tool._sent_in_turn = True
        tool.start_turn()
        assert not tool._sent_in_turn
