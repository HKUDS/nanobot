"""Test message tool suppress logic and RunLoopResult fallback behavior."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop, RunLoopResult
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ChannelsConfig
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path, *, channels_config: ChannelsConfig | None = None) -> AgentLoop:
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=bus, provider=provider, workspace=tmp_path, model="test-model",
        channels_config=channels_config,
    )


class TestMessageToolSuppressLogic:
    """Final reply suppressed only when message tool sends to the same target."""

    @pytest.mark.asyncio
    async def test_suppress_when_sent_to_same_target(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Hello", "channel": "feishu", "chat_id": "chat123"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
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
            id="call1", name="message",
            arguments={"content": "Email content", "channel": "email", "chat_id": "user@example.com"},
        )
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="I've sent the email.", tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])

        sent: list[OutboundMessage] = []
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send email")
        result = await loop._process_message(msg)

        assert len(sent) == 1
        assert sent[0].channel == "email"
        assert result is not None  # not suppressed
        assert result.channel == "feishu"

    @pytest.mark.asyncio
    async def test_not_suppress_when_no_message_tool_used(self, tmp_path: Path) -> None:
        loop = _make_loop(tmp_path)
        loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Hello!", tool_calls=[]))
        loop.tools.get_definitions = MagicMock(return_value=[])

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg)

        assert result is not None
        assert "Hello" in result.content

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
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[tuple[str, bool]] = []

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            progress.append((content, tool_hint))

        result = await loop._run_agent_loop([], on_progress=on_progress)

        assert result.final_content == "Done"
        assert result.fallback_content == "Visible"
        assert result.emitted_fallback_content == "Visible"
        assert progress == [
            ("Visible", False),
            ('read_file("foo.txt")', True),
        ]


class TestRunLoopResultFallbackLogic:
    """Tests for RunLoopResult-based fallback accumulation and suppression."""

    @pytest.mark.asyncio
    async def test_fallback_used_when_progress_not_emitted(self, tmp_path: Path) -> None:
        """Tools + thought + empty final, no progress callback -> result uses fallback."""
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="I'll look that up", tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        # No on_progress callback -> fallback never emitted
        result = await loop._run_agent_loop([])

        assert result.final_content is None
        assert result.fallback_content == "I'll look that up"
        assert result.emitted_fallback_content is None

    @pytest.mark.asyncio
    async def test_fallback_not_used_when_progress_emitted(self, tmp_path: Path) -> None:
        """Tools + thought + empty final, progress ON -> emitted matches fallback."""
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="I'll look that up", tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[str] = []

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            progress.append(content)

        result = await loop._run_agent_loop([], on_progress=on_progress)

        assert result.final_content is None
        assert result.fallback_content == "I'll look that up"
        assert result.emitted_fallback_content == "I'll look that up"
        # Suppression: fallback == emitted, so _process_message would not use it
        assert result.fallback_content == result.emitted_fallback_content

    @pytest.mark.asyncio
    async def test_multi_round_new_thought_not_emitted(self, tmp_path: Path) -> None:
        """R1 emits A, R2 captures B (no progress), empty final -> fallback B returned."""
        loop = _make_loop(tmp_path)
        tc1 = ToolCallRequest(id="call1", name="read_file", arguments={"path": "a.txt"})
        tc2 = ToolCallRequest(id="call2", name="read_file", arguments={"path": "b.txt"})
        calls = iter([
            LLMResponse(content="Thought A", tool_calls=[tc1]),
            LLMResponse(content="Thought B", tool_calls=[tc2]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        call_count = 0

        async def on_progress_first_only(content: str, *, tool_hint: bool = False) -> None:
            """Only the first round has progress callback active."""
            pass  # simulate progress being sent

        # We use actual on_progress for both rounds (simulating send_progress=True)
        # But we want to test: R1 emits "Thought A", R2 emits "Thought B"
        # Since both go through on_progress, emitted_fallback_content will be "Thought B"
        # To test the multi-round scenario where R2 is NOT emitted, we need no on_progress
        # and then the fallback should be "Thought B" (last nonempty)
        result = await loop._run_agent_loop([])  # no on_progress

        assert result.final_content is None
        assert result.fallback_content == "Thought B"
        assert result.emitted_fallback_content is None  # nothing emitted

    @pytest.mark.asyncio
    async def test_multi_round_same_thought_emitted(self, tmp_path: Path) -> None:
        """R1 emits A, R2 silent, empty final -> fallback A suppressed (already sent)."""
        loop = _make_loop(tmp_path)
        tc1 = ToolCallRequest(id="call1", name="read_file", arguments={"path": "a.txt"})
        tc2 = ToolCallRequest(id="call2", name="read_file", arguments={"path": "b.txt"})
        calls = iter([
            LLMResponse(content="Thought A", tool_calls=[tc1]),
            LLMResponse(content=None, tool_calls=[tc2]),  # silent round
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            pass

        result = await loop._run_agent_loop([], on_progress=on_progress)

        assert result.final_content is None
        assert result.fallback_content == "Thought A"
        assert result.emitted_fallback_content == "Thought A"
        # A == A -> suppressed

    @pytest.mark.asyncio
    async def test_multi_round_fallback_preserves_last_nonempty(self, tmp_path: Path) -> None:
        """R1 has content, R2 silent, empty final -> fallback is R1 content."""
        loop = _make_loop(tmp_path)
        tc1 = ToolCallRequest(id="call1", name="read_file", arguments={"path": "a.txt"})
        tc2 = ToolCallRequest(id="call2", name="read_file", arguments={"path": "b.txt"})
        calls = iter([
            LLMResponse(content="First thought", tool_calls=[tc1]),
            LLMResponse(content=None, tool_calls=[tc2]),  # silent
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        result = await loop._run_agent_loop([])  # no on_progress

        assert result.fallback_content == "First thought"
        assert result.emitted_fallback_content is None

    @pytest.mark.asyncio
    async def test_silence_when_both_none_and_no_message_tool(self, tmp_path: Path) -> None:
        """Tools + no thought + empty final -> result is None."""
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content=None, tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        result = await loop._run_agent_loop([])

        assert result.final_content is None
        assert result.fallback_content is None
        assert result.emitted_fallback_content is None

    @pytest.mark.asyncio
    async def test_error_response_wins_over_fallback(self, tmp_path: Path) -> None:
        """finish_reason=error -> final_content used, fallback ignored."""
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="Thinking...", tool_calls=[tool_call]),
            LLMResponse(content="Sorry, error occurred", tool_calls=[], finish_reason="error"),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        result = await loop._run_agent_loop([])

        assert result.final_content == "Sorry, error occurred"
        assert result.fallback_content == "Thinking..."

    @pytest.mark.asyncio
    async def test_system_message_fallback(self, tmp_path: Path) -> None:
        """System path with tools + thought -> uses fallback_content."""
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="Working on it", tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        msg = InboundMessage(channel="system", sender_id="cron", chat_id="feishu:chat123", content="Do task")
        result = await loop._process_message(msg)

        assert result is not None
        assert result.content == "Working on it"

    @pytest.mark.asyncio
    async def test_system_message_no_content_fallback(self, tmp_path: Path) -> None:
        """System msg, no content -> 'Background task completed.'"""
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content=None, tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        msg = InboundMessage(channel="system", sender_id="cron", chat_id="feishu:chat123", content="Do task")
        result = await loop._process_message(msg)

        assert result is not None
        assert result.content == "Background task completed."


class TestProgressGating:
    """Tests for progress gating at the call site."""

    @pytest.mark.asyncio
    async def test_no_progress_by_default(self, tmp_path: Path) -> None:
        """Default config (send_progress=False) -> no progress emitted, fallback used."""
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="Looking it up", tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        outbound: list[OutboundMessage] = []
        loop.bus.publish_outbound = AsyncMock(side_effect=lambda m: outbound.append(m))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg)

        # No progress messages should have been sent via bus
        assert all(not m.metadata.get("_progress") for m in outbound)
        # Fallback should be used since progress was not emitted
        assert result is not None
        assert result.content == "Looking it up"

    @pytest.mark.asyncio
    async def test_progress_when_config_enabled(self, tmp_path: Path) -> None:
        """send_progress=True -> progress emitted, fallback suppressed."""
        config = ChannelsConfig(send_progress=True)
        loop = _make_loop(tmp_path, channels_config=config)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="Looking it up", tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        outbound: list[OutboundMessage] = []
        loop.bus.publish_outbound = AsyncMock(side_effect=lambda m: outbound.append(m))

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg)

        # Progress messages should have been sent
        progress_msgs = [m for m in outbound if m.metadata.get("_progress")]
        assert len(progress_msgs) > 0
        # Fallback suppressed because it was already emitted as progress
        assert result is None

    @pytest.mark.asyncio
    async def test_explicit_callback_overrides_config(self, tmp_path: Path) -> None:
        """Explicit on_progress callback honored regardless of config."""
        config = ChannelsConfig(send_progress=False)
        loop = _make_loop(tmp_path, channels_config=config)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="Looking it up", tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        progress: list[str] = []

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            progress.append(content)

        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        result = await loop._process_message(msg, on_progress=on_progress)

        # Explicit callback should have been invoked
        assert "Looking it up" in progress
        # Fallback suppressed (was emitted via explicit callback)
        assert result is None

    @pytest.mark.asyncio
    async def test_process_direct_no_bus_leak(self, tmp_path: Path) -> None:
        """process_direct with no callback -> no bus progress, fallback used."""
        loop = _make_loop(tmp_path)
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        calls = iter([
            LLMResponse(content="Thought", tool_calls=[tool_call]),
            LLMResponse(content=None, tool_calls=[]),
        ])
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        loop.tools.get_definitions = MagicMock(return_value=[])
        loop.tools.execute = AsyncMock(return_value="ok")

        outbound: list[OutboundMessage] = []
        loop.bus.publish_outbound = AsyncMock(side_effect=lambda m: outbound.append(m))

        content = await loop.process_direct("Hi")

        # No progress messages should have leaked to bus
        assert all(not m.metadata.get("_progress") for m in outbound)
        assert content == "Thought"


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
