"""Tests for WeCom progress notification and streaming result."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.wecom import WecomChannel, WecomConfig
from nanobot.bus.queue import MessageBus


def _make_channel(streaming: bool = True) -> WecomChannel:
    """Create a WecomChannel with mocked dependencies."""
    config = WecomConfig(
        enabled=True,
        bot_id="test_bot",
        secret="test_secret",
        streaming=streaming,
    )
    bus = MagicMock(spec=MessageBus)
    return WecomChannel(config, bus)


class TestWecomProgressNotification:
    """Test progress notification flow."""

    @pytest.mark.asyncio
    async def test_first_progress_sends_starting_message(self):
        """First progress message should send '正在处理...'."""
        channel = _make_channel()
        channel._client = MagicMock()
        channel._client.reply_stream = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_123"
        channel._chat_frames = {"test_chat": MagicMock()}

        msg = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="Processing data...",
            metadata={"_progress": True},
        )

        await channel.send(msg)

        # Should send "正在处理..." first, then the content
        assert channel._client.reply_stream.call_count == 2
        first_call = channel._client.reply_stream.call_args_list[0]
        assert "正在处理..." in first_call.args[2]
        assert first_call.kwargs.get('finish') == False  # finish=False

    @pytest.mark.asyncio
    async def test_subsequent_progress_reuses_stream_id(self):
        """Subsequent progress messages should reuse the same stream ID."""
        channel = _make_channel()
        channel._client = MagicMock()
        channel._client.reply_stream = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_123"
        channel._chat_frames = {"test_chat": MagicMock()}
        channel._stream_ids = {"test_chat": "existing_stream_456"}

        msg = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="Still processing...",
            metadata={"_progress": True},
        )

        await channel.send(msg)

        # Should reuse existing stream ID
        call_args = channel._client.reply_stream.call_args
        assert call_args.args[1] == "existing_stream_456"
        assert call_args.kwargs.get('finish') == False  # finish=False

    @pytest.mark.asyncio
    async def test_final_message_ends_progress_stream(self):
        """Final message should end progress stream with '处理完成'."""
        channel = _make_channel()
        channel._client = MagicMock()
        channel._client.reply_stream = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_123"
        channel._chat_frames = {"test_chat": MagicMock()}
        channel._stream_ids = {"test_chat": "progress_stream_789"}

        msg = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="Final result",
        )

        await channel.send(msg)

        # Should send "处理完成" to end progress stream
        end_call = channel._client.reply_stream.call_args_list[0]
        assert "处理完成" in end_call.args[2]
        assert end_call.kwargs.get('finish') == True  # finish=True

    @pytest.mark.asyncio
    async def test_final_result_with_streaming_enabled(self):
        """Final result should be streamed when streaming=True."""
        channel = _make_channel(streaming=True)
        channel._client = MagicMock()
        channel._client.reply_stream = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_abc"
        channel._chat_frames = {"test_chat": MagicMock()}

        msg = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="Result content",
        )

        await channel.send(msg)

        # Should use reply_stream for result
        result_call = channel._client.reply_stream.call_args
        assert result_call.args[2] == "Result content"
        assert result_call.kwargs.get('finish') == True  # finish=True

    @pytest.mark.asyncio
    async def test_final_result_with_streaming_disabled(self):
        """Final result should use reply() when streaming=False."""
        channel = _make_channel(streaming=False)
        channel._client = MagicMock()
        channel._client.reply = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_xyz"
        channel._chat_frames = {"test_chat": MagicMock()}

        msg = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="Result content",
        )

        await channel.send(msg)

        # Should use reply() for normal message
        channel._client.reply.assert_called_once()
        call_args = channel._client.reply.call_args
        assert call_args.args[1] == "Result content"

    @pytest.mark.asyncio
    async def test_complete_flow_progress_then_result(self):
        """Test complete flow: progress updates then final result."""
        channel = _make_channel(streaming=True)
        channel._client = MagicMock()
        channel._client.reply_stream = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_stream"
        channel._chat_frames = {"test_chat": MagicMock()}

        # Progress message 1
        msg1 = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="Step 1 done",
            metadata={"_progress": True},
        )
        await channel.send(msg1)

        # Progress message 2
        msg2 = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="Step 2 done",
            metadata={"_progress": True},
        )
        await channel.send(msg2)

        # Final result
        msg3 = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="All done!",
        )
        await channel.send(msg3)

        # Should have: "正在处理...", progress1, progress2, "处理完成", result
        assert channel._client.reply_stream.call_count == 5

    @pytest.mark.asyncio
    async def test_empty_content_sends_starting_message(self):
        """Empty progress content should still send '正在处理...'."""
        channel = _make_channel()
        channel._client = MagicMock()
        channel._client.reply_stream = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_123"
        channel._chat_frames = {"test_chat": MagicMock()}

        msg = OutboundMessage(
            channel="wecom",
            chat_id="test_chat",
            content="",
            metadata={"_progress": True},
        )

        await channel.send(msg)

        # Should still send "正在处理..."
        channel._client.reply_stream.assert_called_once()
        call_args = channel._client.reply_stream.call_args
        assert "正在处理..." in call_args.args[2]

    @pytest.mark.asyncio
    async def test_no_frame_for_chat(self):
        """Should handle missing frame gracefully."""
        channel = _make_channel()
        channel._client = MagicMock()
        channel._chat_frames = {}  # No frame for this chat

        msg = OutboundMessage(
            channel="wecom",
            chat_id="unknown_chat",
            content="Hello",
        )

        # Should not raise, just log warning
        await channel.send(msg)

    @pytest.mark.asyncio
    async def test_send_delta_accumulates_text(self):
        """send_delta should accumulate text across calls."""
        channel = _make_channel()
        channel._client = MagicMock()
        channel._client.reply_stream = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_delta"
        channel._chat_frames = {"test_chat": MagicMock()}

        # First delta
        await channel.send_delta("test_chat", "Hello ", finish=False)

        # Second delta
        await channel.send_delta("test_chat", "world!", finish=False)

        # Check accumulated text in second call
        second_call = channel._client.reply_stream.call_args
        assert second_call.args[2] == "Hello world!"

    @pytest.mark.asyncio
    async def test_send_delta_ends_stream(self):
        """send_delta with finish=True should end the stream."""
        channel = _make_channel()
        channel._client = MagicMock()
        channel._client.reply_stream = AsyncMock()
        channel._generate_req_id = lambda prefix: f"{prefix}_delta"
        channel._chat_frames = {"test_chat": MagicMock()}

        await channel.send_delta("test_chat", "Final chunk", finish=True)

        # Should have finish=True
        call_args = channel._client.reply_stream.call_args
        assert call_args.kwargs.get('finish') == True

        # Should clean up buffers
        assert "test_chat" not in channel._result_stream_ids
        assert "test_chat" not in channel._result_stream_bufs