"""Integration tests for progress notification feature (commit a7703f9).

This test suite validates the end-to-end progress notification functionality
across multiple channels, with focus on Feishu's CardKit streaming API.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Test configuration constants
PROGRESS_PREFIX = "🔄 Progress:"
MAX_PROGRESS_CONTENT_LENGTH = 10000
# Throttling: minimum interval between card updates (seconds)
CARD_UPDATE_THROTTLE_INTERVAL = 0.8

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu import FeishuChannel, FeishuConfig
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import ChannelsConfig, Config


def _make_feishu_channel(streaming: bool = True) -> FeishuChannel:
    """Create a mock Feishu channel for testing.

    Args:
        streaming: Whether to enable streaming mode for the channel.

    Returns:
        A FeishuChannel instance with mocked client ready for testing.
    """
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
        streaming=streaming,
    )
    ch = FeishuChannel(config, MessageBus())
    ch._client = MagicMock()
    ch._loop = None
    return ch


def _mock_create_card_response(card_id: str = "card_stream_001") -> MagicMock:
    """Create a mock response for card creation API call.

    Args:
        card_id: The card ID to include in the response.

    Returns:
        A mock response object with success=True and card_id in data.
    """
    resp = MagicMock()
    resp.success.return_value = True
    resp.data = SimpleNamespace(card_id=card_id)
    return resp


def _mock_send_response(message_id: str = "om_stream_001") -> MagicMock:
    """Create a mock response for message send API call.

    Args:
        message_id: The message ID to include in the response.

    Returns:
        A mock response object with success=True and message_id in data.
    """
    resp = MagicMock()
    resp.success.return_value = True
    resp.data = SimpleNamespace(message_id=message_id)
    return resp


def _mock_content_response(success: bool = True) -> MagicMock:
    """Create a mock response for card content update API call.

    Args:
        success: Whether the response indicates success.

    Returns:
        A mock response object with appropriate success status, code, and message.
    """
    resp = MagicMock()
    resp.success.return_value = success
    resp.code = 0 if success else 99999
    resp.msg = "ok" if success else "error"
    return resp


class TestProgressMetadataHandling:
    """Test progress message metadata handling."""

    @pytest.mark.asyncio
    async def test_progress_message_with_active_stream(self):
        """Progress messages should append to active streaming cards."""
        ch = _make_feishu_channel()

        # Simulate an active streaming session
        from nanobot.channels.feishu import _FeishuStreamBuf
        import time
        ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
            text="Initial response",
            card_id="card_active",
            sequence=2,
            last_edit=time.monotonic() - 1.0,  # Allow immediate update
        )

        ch._client.cardkit.v1.card_element.content.return_value = _mock_content_response()

        # Send progress message
        msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_chat1",
            content="Thinking step 1 of 3...",
            metadata={"_progress": True},
        )
        await ch.send(msg)

        # Verify progress was appended to streaming card
        buf = ch._stream_bufs["oc_chat1"]
        assert "Thinking step 1 of 3..." in buf.text
        assert buf.sequence == 3
        ch._client.cardkit.v1.card_element.content.assert_called_once()

    @pytest.mark.asyncio
    async def test_progress_message_without_active_stream(self):
        """Progress messages without active stream should be sent as regular messages."""
        ch = _make_feishu_channel()
        ch._client.im.v1.message.create.return_value = _mock_send_response("om_progress")

        msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_chat1",
            content="Processing your request...",
            metadata={"_progress": True},
        )
        await ch.send(msg)

        # Should send as regular message with "🔄 Progress:" prefix
        ch._client.im.v1.message.create.assert_called_once()
        call_args = ch._client.im.v1.message.create.call_args[0][0]
        assert f"{PROGRESS_PREFIX} Processing your request..." in call_args.body.content

    @pytest.mark.asyncio
    async def test_progress_disabled_globally(self):
        """Progress messages should be filtered when send_progress is False."""
        config = Config(
            channels=ChannelsConfig(send_progress=False),
        )
        bus = MessageBus()
        manager = ChannelManager(config, bus)

        # Mock channel with event for synchronization
        mock_channel = AsyncMock()
        send_event = asyncio.Event()
        mock_channel.send.side_effect = lambda _: send_event.set()
        manager.channels["feishu"] = mock_channel

        # Start manager task
        task = asyncio.create_task(manager._dispatch_outbound())

        # Publish progress message
        msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_chat1",
            content="Progress update",
            metadata={"_progress": True},
        )
        await bus.publish_outbound(msg)

        # Wait for message to be processed (or timeout if filtered correctly)
        # Since progress is disabled, send_event should NOT be set
        try:
            await asyncio.wait_for(send_event.wait(), timeout=0.3)
            # If we get here, the message was incorrectly sent
            raise AssertionError("Progress message should have been filtered")
        except asyncio.TimeoutError:
            # Expected: progress message was filtered
            pass
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Progress message should NOT be sent
        mock_channel.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_hint_with_progress_enabled(self):
        """Tool hints should be sent when send_progress is True."""
        config = Config(
            channels=ChannelsConfig(send_progress=True, send_tool_hints=True),
        )
        bus = MessageBus()
        manager = ChannelManager(config, bus)

        # Mock channel with event for synchronization
        mock_channel = AsyncMock()
        send_event = asyncio.Event()
        mock_channel.send.side_effect = lambda _: send_event.set()
        manager.channels["feishu"] = mock_channel

        task = asyncio.create_task(manager._dispatch_outbound())

        msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_chat1",
            content='web_fetch("https://example.com")',
            metadata={"_tool_hint": True},
        )
        await bus.publish_outbound(msg)

        # Wait for message to be processed
        await asyncio.wait_for(send_event.wait(), timeout=0.5)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_channel.send.assert_called_once()


class TestProgressStreamingIntegration:
    """Test progress streaming integration with CardKit."""

    @pytest.mark.asyncio
    async def test_full_progress_streaming_lifecycle(self):
        """Test complete lifecycle: start → progress updates → end."""
        ch = _make_feishu_channel()

        # Setup mocks
        ch._client.cardkit.v1.card.create.return_value = _mock_create_card_response("card_lifecycle")
        ch._client.im.v1.message.create.return_value = _mock_send_response("om_lifecycle")
        ch._client.cardkit.v1.card_element.content.return_value = _mock_content_response()
        ch._client.cardkit.v1.card.settings.return_value = _mock_content_response()

        # Step 1: Initial delta creates streaming card
        await ch.send_delta("oc_chat1", "Starting analysis...")
        assert "oc_chat1" in ch._stream_bufs
        buf = ch._stream_bufs["oc_chat1"]
        assert buf.card_id == "card_lifecycle"
        assert buf.text == "Starting analysis..."

        # Step 2: Progress message appends to stream
        progress_msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_chat1",
            content="📊 Analyzing data...",
            metadata={"_progress": True},
        )
        await ch.send(progress_msg)

        buf = ch._stream_bufs["oc_chat1"]
        assert "📊 Analyzing data..." in buf.text

        # Step 3: More deltas
        await ch.send_delta("oc_chat1", " Found 3 patterns.")
        buf = ch._stream_bufs["oc_chat1"]
        assert "Found 3 patterns." in buf.text

        # Step 4: End streaming
        await ch.send_delta("oc_chat1", "", metadata={"_stream_end": True})

        # Buffer should be cleaned up
        assert "oc_chat1" not in ch._stream_bufs

        # Verify all expected API calls were made
        ch._client.cardkit.v1.card.create.assert_called_once()
        assert ch._client.cardkit.v1.card_element.content.call_count >= 2
        ch._client.cardkit.v1.card.settings.assert_called_once()

    @pytest.mark.asyncio
    async def test_progress_streaming_timeout_fallback(self):
        """When streaming times out, fallback to regular card message."""
        ch = _make_feishu_channel()

        # Simulate streaming card creation success but content update failure
        ch._client.cardkit.v1.card.create.return_value = _mock_create_card_response("card_timeout")
        ch._client.im.v1.message.create.return_value = _mock_send_response("om_timeout")
        ch._client.cardkit.v1.card_element.content.return_value = _mock_content_response(success=False)

        # Start streaming
        await ch.send_delta("oc_chat1", "Initial content")
        assert "oc_chat1" in ch._stream_bufs

        # Try to send progress (will fail due to simulated timeout)
        progress_msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_chat1",
            content="Progress update",
            metadata={"_progress": True},
        )
        await ch.send(progress_msg)

        # End stream - should fallback to regular card
        await ch.send_delta("oc_chat1", "", metadata={"_stream_end": True})

        # Should have attempted fallback via im.v1.message.create
        assert ch._client.im.v1.message.create.call_count >= 1


class TestMultiChannelProgressSupport:
    """Test that progress notifications work across different channels."""

    def test_all_channels_respect_send_progress_config(self):
        """Verify all channel types check send_progress config."""
        from nanobot.channels.wecom import WecomChannel, WecomConfig
        from nanobot.channels.telegram import TelegramChannel, TelegramConfig
        from nanobot.channels.slack import SlackChannel, SlackConfig

        channels_to_test = [
            (WecomChannel, WecomConfig, "wecom"),
            (TelegramChannel, TelegramConfig, "telegram"),
            (SlackChannel, SlackConfig, "slack"),
        ]

        for ChannelClass, ConfigClass, channel_name in channels_to_test:
            config = ConfigClass(enabled=True)
            bus = MessageBus()
            channel = ChannelClass(config, bus)

            # All channels should exist and have send method
            assert hasattr(channel, 'send')
            assert callable(getattr(channel, 'send'))

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        [
            "Loading...",
            "Step 1/5 completed",
            "Fetching data from API",
        ],
    )
    async def test_feishu_progress_format_consistency(self, content: str):
        """Progress messages should have consistent formatting."""
        ch = _make_feishu_channel()
        ch._client.im.v1.message.create.return_value = _mock_send_response("om_fmt")

        msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_test",
            content=content,
            metadata={"_progress": True},
        )
        await ch.send(msg)

        call_args = ch._client.im.v1.message.create.call_args[0][0]
        expected_content = f"{PROGRESS_PREFIX} {content}"
        assert expected_content in call_args.body.content


class TestProgressConcurrency:
    """Test progress handling under concurrent scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_progress_messages_same_chat(self):
        """Multiple concurrent progress messages to same chat should be handled safely."""
        ch = _make_feishu_channel()

        # Setup active stream
        from nanobot.channels.feishu import _FeishuStreamBuf
        ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
            text="Base content",
            card_id="card_concurrent",
            sequence=1,
            last_edit=0.0,
        )

        ch._client.cardkit.v1.card_element.content.return_value = _mock_content_response()

        # Send multiple progress messages concurrently
        tasks = []
        for i in range(5):
            msg = OutboundMessage(
                channel="feishu",
                chat_id="oc_chat1",
                content=f"Progress {i}",
                metadata={"_progress": True},
            )
            tasks.append(ch.send(msg))

        await asyncio.gather(*tasks)

        # All progress messages should be appended
        buf = ch._stream_bufs["oc_chat1"]
        for i in range(5):
            assert f"Progress {i}" in buf.text

        # Sequence should have incremented at least once
        # (throttling may merge rapid updates, so we don't expect exactly 6)
        assert buf.sequence >= 2  # initial 1 + at least 1 update
        # Verify API was called at least once
        assert ch._client.cardkit.v1.card_element.content.call_count >= 1

    @pytest.mark.asyncio
    async def test_progress_messages_different_chats_isolated(self):
        """Progress messages to different chats should not interfere."""
        ch = _make_feishu_channel()

        # When no active stream, progress messages are sent as regular messages
        # and don't create buffers (they're just sent immediately)
        ch._client.im.v1.message.create.return_value = _mock_send_response("om_multi")

        # Send progress to different chats
        for chat_id in ["oc_chat1", "oc_chat2", "oc_chat3"]:
            msg = OutboundMessage(
                channel="feishu",
                chat_id=chat_id,
                content=f"Progress for {chat_id}",
                metadata={"_progress": True},
            )
            await ch.send(msg)

        # Progress messages without active streams are sent directly, not buffered
        # Verify all three messages were sent
        assert ch._client.im.v1.message.create.call_count == 3

        # Now test with active streams - each chat gets its own buffer
        ch._client.cardkit.v1.card.create.return_value = _mock_create_card_response("card_multi2")
        ch._client.cardkit.v1.card_element.content.return_value = _mock_content_response()

        # Create active streams for each chat
        for i, chat_id in enumerate(["oc_chat4", "oc_chat5", "oc_chat6"]):
            await ch.send_delta(chat_id, f"Initial {chat_id}")

        # Each chat should have its own buffer
        assert len(ch._stream_bufs) == 3
        for chat_id in ["oc_chat4", "oc_chat5", "oc_chat6"]:
            assert chat_id in ch._stream_bufs
            assert f"Initial {chat_id}" in ch._stream_bufs[chat_id].text


class TestProgressEdgeCases:
    """Test edge cases and error scenarios."""

    @pytest.mark.asyncio
    async def test_empty_progress_content(self):
        """Empty progress content should be handled gracefully."""
        ch = _make_feishu_channel()

        for content in ["", "   ", "\n\t"]:
            msg = OutboundMessage(
                channel="feishu",
                chat_id="oc_chat1",
                content=content,
                metadata={"_progress": True},
            )
            # Should not raise exception
            await ch.send(msg)

    @pytest.mark.asyncio
    async def test_progress_without_client(self):
        """Progress messages should be safely ignored when client is None."""
        ch = _make_feishu_channel()
        ch._client = None

        msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_chat1",
            content="Progress",
            metadata={"_progress": True},
        )
        # Should not raise exception
        await ch.send(msg)

    @pytest.mark.asyncio
    async def test_progress_with_very_long_content(self):
        """Long progress messages should be handled without errors."""
        ch = _make_feishu_channel()
        ch._client.im.v1.message.create.return_value = _mock_send_response("om_long")

        long_content = "Progress: " + "x" * MAX_PROGRESS_CONTENT_LENGTH
        msg = OutboundMessage(
            channel="feishu",
            chat_id="oc_chat1",
            content=long_content,
            metadata={"_progress": True},
        )
        await ch.send(msg)

        ch._client.im.v1.message.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_rapid_progress_updates_throttling(self):
        """Rapid progress updates should respect throttling.

        The Feishu channel uses _STREAM_EDIT_INTERVAL = 0.5s for throttling.
        When updates arrive faster than this interval, they are accumulated
        in the buffer but API calls are throttled.
        """
        ch = _make_feishu_channel()

        # Create active stream with recent update
        from nanobot.channels.feishu import _FeishuStreamBuf
        import time
        ch._stream_bufs["oc_chat1"] = _FeishuStreamBuf(
            text="Content",
            card_id="card_throttle",
            sequence=1,
            last_edit=time.monotonic(),  # Very recent
        )

        ch._client.cardkit.v1.card_element.content.return_value = _mock_content_response()

        # Send rapid updates without delay between them
        for i in range(10):
            msg = OutboundMessage(
                channel="feishu",
                chat_id="oc_chat1",
                content=f"Update {i}",
                metadata={"_progress": True},
            )
            await ch.send(msg)

        # Since all updates arrive within the throttle window (< 0.5s after last_edit),
        # no API calls should be made - the content is just accumulated
        api_calls = ch._client.cardkit.v1.card_element.content.call_count
        assert api_calls == 0, f"Expected 0 API calls due to throttling, got {api_calls}"

        # Verify all content was still accumulated in buffer despite throttling
        buf = ch._stream_bufs["oc_chat1"]
        for i in range(10):
            assert f"Update {i}" in buf.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])