"""Unit tests for MQTT channel implementation."""

import json
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.mqtt import MQTTChannel
from nanobot.config.schema import MQTTConfig, MQTTTopicConfig, MQTTWillConfig


def _make_config(**overrides) -> MQTTConfig:
    """Create a test MQTT configuration."""
    defaults = {
        "enabled": True,
        "host": "localhost",
        "port": 1883,
        "allow_from": ["*"],
    }
    defaults.update(overrides)
    return MQTTConfig(**defaults)


class TestTopicParsing:
    """Tests for MQTT topic parsing."""

    def test_parse_valid_topic(self) -> None:
        """Valid topic extracts sender_id correctly."""
        channel = MQTTChannel(_make_config(), MessageBus())
        result = channel._parse_topic("nanobot/user123/inbox")
        assert result is not None
        sender_id, chat_id = result
        assert sender_id == "user123"
        assert chat_id == "user123"

    def test_parse_topic_with_dashes(self) -> None:
        """Topic with dashes in sender_id works."""
        channel = MQTTChannel(_make_config(), MessageBus())
        result = channel._parse_topic("nanobot/user-abc-123/inbox")
        assert result is not None
        assert result[0] == "user-abc-123"

    def test_parse_topic_with_underscores(self) -> None:
        """Topic with underscores in sender_id works."""
        channel = MQTTChannel(_make_config(), MessageBus())
        result = channel._parse_topic("nanobot/user_abc_123/inbox")
        assert result is not None
        assert result[0] == "user_abc_123"

    def test_parse_topic_with_special_chars(self) -> None:
        """Topic with special characters in sender_id works."""
        channel = MQTTChannel(_make_config(), MessageBus())
        result = channel._parse_topic("nanobot/device@home/inbox")
        assert result is not None
        assert result[0] == "device@home"

    def test_parse_invalid_topic_wrong_prefix(self) -> None:
        """Invalid topic prefix returns None."""
        channel = MQTTChannel(_make_config(), MessageBus())
        result = channel._parse_topic("other/user123/inbox")
        assert result is None

    def test_parse_invalid_topic_wrong_suffix(self) -> None:
        """Invalid topic suffix returns None."""
        channel = MQTTChannel(_make_config(), MessageBus())
        result = channel._parse_topic("nanobot/user123/outbox")
        assert result is None

    def test_parse_invalid_topic_too_many_levels(self) -> None:
        """Topic with too many levels returns None."""
        channel = MQTTChannel(_make_config(), MessageBus())
        result = channel._parse_topic("nanobot/org/user123/inbox")
        assert result is None

    def test_parse_invalid_topic_too_few_levels(self) -> None:
        """Topic with too few levels returns None."""
        channel = MQTTChannel(_make_config(), MessageBus())
        result = channel._parse_topic("nanobot/user123")
        assert result is None


class TestPayloadDecoding:
    """Tests for MQTT payload decoding."""

    def test_decode_json_payload(self) -> None:
        """JSON payload decodes correctly."""
        channel = MQTTChannel(_make_config(payload_format="json"), MessageBus())
        payload = json.dumps({"content": "Hello", "metadata": {"key": "value"}}).encode()
        content, metadata = channel._decode_payload(payload, "nanobot/test/inbox")
        assert content == "Hello"
        assert metadata == {"key": "value"}

    def test_decode_json_payload_without_metadata(self) -> None:
        """JSON payload without metadata works."""
        channel = MQTTChannel(_make_config(payload_format="json"), MessageBus())
        payload = json.dumps({"content": "Hello"}).encode()
        content, metadata = channel._decode_payload(payload, "nanobot/test/inbox")
        assert content == "Hello"
        assert metadata == {}

    def test_decode_json_payload_plain_string(self) -> None:
        """JSON payload with plain string value works."""
        channel = MQTTChannel(_make_config(payload_format="json"), MessageBus())
        payload = json.dumps("Just a string").encode()
        content, metadata = channel._decode_payload(payload, "nanobot/test/inbox")
        assert content == "Just a string"
        assert metadata == {}

    def test_decode_json_invalid_falls_back(self) -> None:
        """Invalid JSON falls back to plain text."""
        channel = MQTTChannel(_make_config(payload_format="json"), MessageBus())
        payload = b"Not valid JSON"
        content, metadata = channel._decode_payload(payload, "nanobot/test/inbox")
        assert content == "Not valid JSON"
        assert metadata.get("json_parse_error") is True

    def test_decode_text_payload(self) -> None:
        """Text payload decodes as-is."""
        channel = MQTTChannel(_make_config(payload_format="text"), MessageBus())
        payload = b"Plain text message"
        content, metadata = channel._decode_payload(payload, "nanobot/test/inbox")
        assert content == "Plain text message"
        assert metadata == {}

    def test_decode_unicode_payload(self) -> None:
        """Unicode payload decodes correctly."""
        channel = MQTTChannel(_make_config(payload_format="text"), MessageBus())
        payload = "你好世界 🌍".encode("utf-8")
        content, metadata = channel._decode_payload(payload, "nanobot/test/inbox")
        assert content == "你好世界 🌍"
        assert metadata == {}

    def test_decode_invalid_utf8(self) -> None:
        """Invalid UTF-8 returns empty content with error flag."""
        channel = MQTTChannel(_make_config(), MessageBus())
        payload = b"\xff\xfe invalid utf-8"
        content, metadata = channel._decode_payload(payload, "nanobot/test/inbox")
        assert content == ""
        assert metadata.get("decode_error") is True
        assert metadata.get("raw") is True


class TestPayloadEncoding:
    """Tests for MQTT payload encoding."""

    def test_encode_json_payload(self) -> None:
        """JSON payload encodes correctly."""
        channel = MQTTChannel(_make_config(payload_format="json"), MessageBus())
        payload = channel._encode_payload("Hello", {"key": "value"})
        data = json.loads(payload)
        assert data["content"] == "Hello"
        assert data["metadata"] == {"key": "value"}

    def test_encode_json_filters_internal_metadata(self) -> None:
        """Internal metadata (starting with _) is filtered out."""
        channel = MQTTChannel(_make_config(payload_format="json"), MessageBus())
        payload = channel._encode_payload("Hello", {"_internal": "secret", "public": "value"})
        data = json.loads(payload)
        assert "_internal" not in data.get("metadata", {})
        assert data["metadata"]["public"] == "value"

    def test_encode_json_no_metadata(self) -> None:
        """JSON payload without metadata works."""
        channel = MQTTChannel(_make_config(payload_format="json"), MessageBus())
        payload = channel._encode_payload("Hello")
        data = json.loads(payload)
        assert data["content"] == "Hello"
        assert "metadata" not in data

    def test_encode_text_payload(self) -> None:
        """Text payload encodes as-is."""
        channel = MQTTChannel(_make_config(payload_format="text"), MessageBus())
        payload = channel._encode_payload("Hello", {"key": "value"})
        assert payload == b"Hello"

    def test_encode_unicode_payload(self) -> None:
        """Unicode payload encodes correctly."""
        channel = MQTTChannel(_make_config(payload_format="json"), MessageBus())
        payload = channel._encode_payload("你好世界 🌍")
        data = json.loads(payload)
        assert data["content"] == "你好世界 🌍"


class TestTopicBuilding:
    """Tests for outbound topic building."""

    def test_build_publish_topic_default(self) -> None:
        """Default template builds correctly."""
        channel = MQTTChannel(_make_config(), MessageBus())
        topic = channel._build_publish_topic("user123")
        assert topic == "nanobot/user123/outbox"

    def test_build_publish_topic_custom_template(self) -> None:
        """Custom template builds correctly."""
        config = _make_config(publish_topic_template="mybot/{chat_id}/reply")
        channel = MQTTChannel(config, MessageBus())
        topic = channel._build_publish_topic("user123")
        assert topic == "mybot/user123/reply"

    def test_build_publish_topic_special_chars(self) -> None:
        """Topic with special characters in chat_id works."""
        channel = MQTTChannel(_make_config(), MessageBus())
        topic = channel._build_publish_topic("device@home")
        assert topic == "nanobot/device@home/outbox"


class TestAccessControl:
    """Tests for access control (inherited from BaseChannel)."""

    def test_allow_all(self) -> None:
        """Wildcard allows all senders."""
        channel = MQTTChannel(_make_config(allow_from=["*"]), MessageBus())
        assert channel.is_allowed("anyone") is True
        assert channel.is_allowed("user123") is True

    def test_allow_specific(self) -> None:
        """Specific allowlist works."""
        channel = MQTTChannel(_make_config(allow_from=["user123", "user456"]), MessageBus())
        assert channel.is_allowed("user123") is True
        assert channel.is_allowed("user456") is True
        assert channel.is_allowed("user789") is False

    def test_empty_allowlist_denies_all(self) -> None:
        """Empty allowlist denies all."""
        channel = MQTTChannel(_make_config(allow_from=[]), MessageBus())
        assert channel.is_allowed("anyone") is False


    def test_pipe_separated_sender_id(self) -> None:
        """Pipe-separated sender_id matches any part."""
        channel = MQTTChannel(_make_config(allow_from=["user123"]), MessageBus())
        # sender_id can be "id|username" format
        assert channel.is_allowed("user123|myname") is True
        assert channel.is_allowed("other|user123") is True


class TestConfigurationDefaults:
    """Tests for configuration defaults."""

    def test_default_subscribe_topics(self) -> None:
        """Default subscribe topics are set."""
        config = MQTTConfig()
        assert len(config.subscribe_topics) == 1
        assert config.subscribe_topics[0].topic == "nanobot/+/inbox"
        assert config.subscribe_topics[0].qos == 1

    def test_default_connection_settings(self) -> None:
        """Default connection settings are correct."""
        config = MQTTConfig()
        assert config.host == "localhost"
        assert config.port == 1883
        assert config.keepalive == 60
        assert config.clean_session is True

    def test_default_will_settings(self) -> None:
        """Default will settings are correct."""
        config = MQTTConfig()
        assert config.will.enabled is True
        assert config.will.topic == "nanobot/status"
        assert config.will.payload == "offline"

    def test_default_reconnect_settings(self) -> None:
        """Default reconnect settings are correct."""
        config = MQTTConfig()
        assert config.reconnect_min_delay == 1.0
        assert config.reconnect_max_delay == 60.0


@pytest.mark.asyncio
class TestAsyncOperations:
    """Async tests for MQTT channel."""

    async def test_send_without_client_returns_early(self) -> None:
        """Send without connected client returns early without error."""
        channel = MQTTChannel(_make_config(), MessageBus())
        channel._client = None

        # Should not raise an exception
        await channel.send(OutboundMessage(
            channel="mqtt",
            chat_id="user123",
            content="Test message",
        ))

        # Verify state unchanged
        assert channel._client is None

    async def test_stop_sets_running_false(self) -> None:
        """Stop sets running flag to False."""
        channel = MQTTChannel(_make_config(), MessageBus())
        channel._running = True

        await channel.stop()

        assert channel._running is False
        assert channel._client is None
