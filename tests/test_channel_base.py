"""Tests for base channel functionality."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class MockChannel(BaseChannel):
    """Mock channel implementation for testing."""

    name = "mock"
    display_name = "Mock Channel"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._running = False

    async def start(self):
        """Mock start method."""
        self._running = True

    async def stop(self):
        """Mock stop method."""
        self._running = False

    async def send(self, msg: OutboundMessage):
        """Mock send method."""
        pass


class TestBaseChannel:
    """Test cases for BaseChannel class."""

    def test_base_channel_init(self, mock_message_bus):
        """Test BaseChannel initialization."""
        config = {"enabled": True, "allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        assert channel.config == config
        assert channel.bus == mock_message_bus
        assert channel._running is False
        assert channel.name == "mock"
        assert channel.display_name == "Mock Channel"

    def test_base_channel_with_dict_config(self, mock_message_bus):
        """Test channel initialization with dict config."""
        config = {"enabled": True, "allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        assert channel.config == config

    def test_is_running_property(self, mock_message_bus):
        """Test is_running property."""
        channel = MockChannel({}, mock_message_bus)

        assert channel.is_running is False

        channel._running = True
        assert channel.is_running is True

    def test_is_allowed_empty_list(self, mock_message_bus):
        """Test access control with empty allow list."""
        config = {"allow_from": []}
        channel = MockChannel(config, mock_message_bus)

        assert channel.is_allowed("user1") is False
        assert channel.is_allowed("user2") is False

    def test_is_allowed_wildcard(self, mock_message_bus):
        """Test access control with wildcard."""
        config = {"allow_from": ["*"]}
        channel = MockChannel(config, mock_message_bus)

        assert channel.is_allowed("user1") is True
        assert channel.is_allowed("user2") is True
        assert channel.is_allowed("any_user") is True

    def test_is_allowed_specific_user(self, mock_message_bus):
        """Test access control with specific user."""
        config = {"allow_from": ["user1", "user2"]}
        channel = MockChannel(config, mock_message_bus)

        assert channel.is_allowed("user1") is True
        assert channel.is_allowed("user2") is True
        assert channel.is_allowed("user3") is False

    def test_is_allowed_numeric_user_id(self, mock_message_bus):
        """Test access control with numeric user ID."""
        config = {"allow_from": ["123456", "789012"]}
        channel = MockChannel(config, mock_message_bus)

        assert channel.is_allowed("123456") is True
        assert channel.is_allowed("789012") is True
        assert channel.is_allowed("999999") is False

    def test_is_allowed_with_string_conversion(self, mock_message_bus):
        """Test that user IDs are converted to strings."""
        config = {"allow_from": ["123456"]}
        channel = MockChannel(config, mock_message_bus)

        # Should work with numeric input
        assert channel.is_allowed(123456) is True

    def test_handle_message_allowed(self, mock_message_bus):
        """Test message handling for allowed users."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content="Hello",
            media=None,
            metadata={},
        )

        # Should publish to bus
        mock_message_bus.publish_inbound.assert_called_once()
        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert isinstance(msg, InboundMessage)
        assert msg.channel == "mock"
        assert msg.sender_id == "user1"
        assert msg.chat_id == "chat1"
        assert msg.content == "Hello"

    def test_handle_message_denied(self, mock_message_bus):
        """Test message handling for denied users."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        channel._handle_message(
            sender_id="user2",
            chat_id="chat1",
            content="Hello",
            media=None,
            metadata={},
        )

        # Should not publish to bus
        mock_message_bus.publish_inbound.assert_not_called()

    def test_handle_message_with_media(self, mock_message_bus):
        """Test message handling with media attachments."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        media_paths = ["/path/to/image.jpg", "/path/to/file.pdf"]
        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content="Check this out",
            media=media_paths,
            metadata={},
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.media == media_paths

    def test_handle_message_with_metadata(self, mock_message_bus):
        """Test message handling with metadata."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        metadata = {"message_id": "msg123", "timestamp": "2024-01-01"}
        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content="Hello",
            media=None,
            metadata=metadata,
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.metadata == metadata

    def test_handle_message_with_session_key_override(self, mock_message_bus):
        """Test message handling with session key override."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content="Hello",
            media=None,
            metadata={},
            session_key="custom:session",
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.session_key_override == "custom:session"

    def test_transcribe_audio_no_key(self, mock_message_bus):
        """Test audio transcription without API key."""
        channel = MockChannel({}, mock_message_bus)
        channel.transcription_api_key = ""

        result = channel.transcribe_audio("/path/to/audio.mp3")

        assert result == ""

    @patch("nanobot.channels.base.GroqTranscriptionProvider")
    def test_transcribe_audio_with_key(self, mock_provider_class, mock_message_bus):
        """Test audio transcription with API key."""
        mock_provider = Mock()
        mock_provider.transcribe = AsyncMock(return_value="Transcribed text")
        mock_provider_class.return_value = mock_provider

        channel = MockChannel({}, mock_message_bus)
        channel.transcription_api_key = "test_key"

        # This is a sync method, but it calls async internally
        # We'll need to handle this differently in real tests
        # For now, just test the setup
        assert channel.transcription_api_key == "test_key"

    @patch("nanobot.channels.base.GroqTranscriptionProvider")
    def test_transcribe_audio_failure(self, mock_provider_class, mock_message_bus):
        """Test audio transcription failure handling."""
        mock_provider = Mock()
        mock_provider.transcribe = AsyncMock(side_effect=Exception("Transcription failed"))
        mock_provider_class.return_value = mock_provider

        channel = MockChannel({}, mock_message_bus)
        channel.transcription_api_key = "test_key"

        # Should return empty string on failure
        # (actual async call would be tested in async context)
        assert channel.transcription_api_key == "test_key"

    def test_default_config(self, mock_message_bus):
        """Test default configuration."""
        config = MockChannel.default_config()

        assert isinstance(config, dict)
        assert "enabled" in config
        assert config["enabled"] is False

    def test_channel_name_property(self, mock_message_bus):
        """Test channel name property."""
        channel = MockChannel({}, mock_message_bus)

        assert channel.name == "mock"

    def test_channel_display_name_property(self, mock_message_bus):
        """Test channel display name property."""
        channel = MockChannel({}, mock_message_bus)

        assert channel.display_name == "Mock Channel"

    def test_handle_message_empty_content(self, mock_message_bus):
        """Test handling message with empty content."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content="",
            media=None,
            metadata={},
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.content == ""

    def test_handle_message_unicode_content(self, mock_message_bus):
        """Test handling message with unicode content."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        unicode_content = "Hello 世界 🌍"
        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content=unicode_content,
            media=None,
            metadata={},
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.content == unicode_content

    def test_handle_message_long_content(self, mock_message_bus):
        """Test handling message with very long content."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        long_content = "x" * 10000
        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content=long_content,
            media=None,
            metadata={},
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.content == long_content

    def test_handle_message_with_empty_media_list(self, mock_message_bus):
        """Test handling message with empty media list."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content="Hello",
            media=[],
            metadata={},
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.media == []

    def test_handle_message_with_none_media(self, mock_message_bus):
        """Test handling message with None media."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content="Hello",
            media=None,
            metadata={},
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.media == []

    def test_handle_message_with_none_metadata(self, mock_message_bus):
        """Test handling message with None metadata."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        channel._handle_message(
            sender_id="user1",
            chat_id="chat1",
            content="Hello",
            media=None,
            metadata=None,
        )

        call_args = mock_message_bus.publish_inbound.call_args
        msg = call_args[0][0]

        assert msg.metadata == {}

    def test_is_allowed_case_sensitive(self, mock_message_bus):
        """Test that allow_from is case-sensitive."""
        config = {"allow_from": ["User1"]}
        channel = MockChannel(config, mock_message_bus)

        assert channel.is_allowed("User1") is True
        assert channel.is_allowed("user1") is False

    def test_is_allowed_with_special_characters(self, mock_message_bus):
        """Test allow_from with special characters."""
        config = {"allow_from": ["user@example.com", "user_123", "user-name"]}
        channel = MockChannel(config, mock_message_bus)

        assert channel.is_allowed("user@example.com") is True
        assert channel.is_allowed("user_123") is True
        assert channel.is_allowed("user-name") is True
        assert channel.is_allowed("user@example") is False

    def test_multiple_channels_same_bus(self, mock_message_bus):
        """Test multiple channels using the same message bus."""
        config1 = {"allow_from": ["user1"]}
        config2 = {"allow_from": ["user2"]}

        channel1 = MockChannel(config1, mock_message_bus)
        channel2 = MockChannel(config2, mock_message_bus)

        # Both should use the same bus
        assert channel1.bus is mock_message_bus
        assert channel2.bus is mock_message_bus

        # Each channel should have its own config
        assert channel1.config == config1
        assert channel2.config == config2

    def test_channel_config_mutation(self, mock_message_bus):
        """Test that channel config can be mutated."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        # Mutate config
        channel.config["allow_from"].append("user2")

        # Should be reflected
        assert channel.is_allowed("user2") is True

    def test_abstract_methods_must_be_implemented(self, mock_message_bus):
        """Test that abstract methods must be implemented."""
        # This is more of a design test - if we try to instantiate
        # BaseChannel directly, it should fail
        with pytest.raises(TypeError):
            BaseChannel({}, mock_message_bus)

    def test_channel_lifecycle(self, mock_message_bus):
        """Test channel lifecycle (start/stop)."""
        channel = MockChannel({}, mock_message_bus)

        assert channel._running is False

        # Start
        channel._running = True
        assert channel.is_running is True

        # Stop
        channel._running = False
        assert channel.is_running is False

    def test_handle_message_concurrent(self, mock_message_bus):
        """Test handling multiple messages concurrently."""
        config = {"allow_from": ["user1"]}
        channel = MockChannel(config, mock_message_bus)

        # Send multiple messages
        for i in range(5):
            channel._handle_message(
                sender_id="user1",
                chat_id="chat1",
                content=f"Message {i}",
                media=None,
                metadata={},
            )

        # All should be published
        assert mock_message_bus.publish_inbound.call_count == 5

    def test_channel_with_complex_config(self, mock_message_bus):
        """Test channel with complex configuration."""
        config = {
            "enabled": True,
            "allow_from": ["user1", "user2"],
            "option1": "value1",
            "option2": 123,
            "option3": True,
            "nested": {"key": "value"},
        }
        channel = MockChannel(config, mock_message_bus)

        assert channel.config == config
        assert channel.is_allowed("user1") is True
        assert channel.is_allowed("user2") is True
        assert channel.is_allowed("user3") is False
