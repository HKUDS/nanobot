"""Tests for FeishuChannel tool hint code block formatting."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pytest import mark

# Check optional Feishu dependencies before running tests
try:
    from nanobot.channels import feishu
    FEISHU_AVAILABLE = getattr(feishu, "FEISHU_AVAILABLE", False)
except ImportError:
    FEISHU_AVAILABLE = False

if not FEISHU_AVAILABLE:
    pytest.skip("Feishu dependencies not installed (lark-oapi)", allow_module_level=True)

from nanobot.bus.events import OutboundMessage
from nanobot.channels.feishu import FeishuChannel


@pytest.fixture
def mock_feishu_channel():
    """Create a FeishuChannel with mocked client."""
    config = MagicMock()
    config.app_id = "test_app_id"
    config.app_secret = "test_app_secret"
    config.encrypt_key = None
    config.verification_token = None
    bus = MagicMock()
    channel = FeishuChannel(config, bus)
    channel._client = MagicMock()  # Simulate initialized client
    return channel


@mark.asyncio
async def test_tool_hint_sends_code_message(mock_feishu_channel):
    """Tool hint messages should be sent as interactive cards with code blocks."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='web_search("test query")',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        # Verify interactive message with card was sent
        assert mock_send.call_count == 1
        call_args = mock_send.call_args[0]
        receive_id_type, receive_id, msg_type, content = call_args

        assert receive_id_type == "chat_id"
        assert receive_id == "oc_123456"
        assert msg_type == "interactive"

        # Parse content to verify card structure
        card = json.loads(content)
        assert card["config"]["wide_screen_mode"] is True
        assert len(card["elements"]) == 1
        assert card["elements"][0]["tag"] == "markdown"
        # Check that code block is properly formatted with language hint
        expected_md = "**Tool Calls**\n\n```text\nweb_search(\"test query\")\n```"
        assert card["elements"][0]["content"] == expected_md


@mark.asyncio
async def test_tool_hint_empty_content_does_not_send(mock_feishu_channel):
    """Empty tool hint messages should not be sent."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content="   ",  # whitespace only
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        # Should not send any message
        mock_send.assert_not_called()


@mark.asyncio
async def test_tool_hint_without_metadata_sends_as_normal(mock_feishu_channel):
    """Regular messages without _tool_hint should use normal formatting."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content="Hello, world!",
        metadata={}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        # Should send as text message (detected format)
        assert mock_send.call_count == 1
        call_args = mock_send.call_args[0]
        _, _, msg_type, content = call_args
        assert msg_type == "text"
        assert json.loads(content) == {"text": "Hello, world!"}


@mark.asyncio
async def test_tool_hint_multiple_tools_in_one_message(mock_feishu_channel):
    """Multiple tool calls should be displayed each on its own line in a code block."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='web_search("query"), read_file("/path/to/file")',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        call_args = mock_send.call_args[0]
        msg_type = call_args[2]
        content = json.loads(call_args[3])
        assert msg_type == "interactive"
        # Each tool call should be on its own line
        expected_md = "**Tool Calls**\n\n```text\nweb_search(\"query\"),\nread_file(\"/path/to/file\")\n```"
        assert content["elements"][0]["content"] == expected_md


@mark.asyncio
async def test_tool_hint_new_format_basic(mock_feishu_channel):
    """New format hints (read path, grep "pattern") should parse correctly."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='read src/main.py, grep "TODO"',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        content = json.loads(mock_send.call_args[0][3])
        md = content["elements"][0]["content"]
        assert "read src/main.py" in md
        assert 'grep "TODO"' in md


@mark.asyncio
async def test_tool_hint_new_format_with_comma_in_quotes(mock_feishu_channel):
    """Commas inside quoted arguments must not cause incorrect line splits."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='grep "hello, world", $ echo test',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        content = json.loads(mock_send.call_args[0][3])
        md = content["elements"][0]["content"]
        # The comma inside quotes should NOT cause a line break
        assert 'grep "hello, world"' in md
        assert "$ echo test" in md


@mark.asyncio
async def test_tool_hint_new_format_with_folding(mock_feishu_channel):
    """Folded calls (× N) should display on separate lines."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='read path × 3, grep "pattern"',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        content = json.loads(mock_send.call_args[0][3])
        md = content["elements"][0]["content"]
        assert "\u00d7 3" in md
        assert 'grep "pattern"' in md


@mark.asyncio
async def test_tool_hint_new_format_mcp(mock_feishu_channel):
    """MCP tool format (server::tool) should parse correctly."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='4_5v::analyze_image("photo.jpg")',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        content = json.loads(mock_send.call_args[0][3])
        md = content["elements"][0]["content"]
        assert "4_5v::analyze_image" in md
async def test_tool_hint_keeps_commas_inside_arguments(mock_feishu_channel):
    """Commas inside a single tool argument must not be split onto a new line."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='web_search("foo, bar"), read_file("/path/to/file")',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        content = json.loads(mock_send.call_args[0][3])
        expected_md = (
            "**Tool Calls**\n\n```text\n"
            "web_search(\"foo, bar\"),\n"
            "read_file(\"/path/to/file\")\n```"
        )
        assert content["elements"][0]["content"] == expected_md
