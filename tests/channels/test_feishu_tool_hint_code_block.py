"""Tests for FeishuChannel tool hint formatting."""

import json
from types import SimpleNamespace
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
    config.tool_hint_prefix = "\U0001f527"  # 🔧
    bus = MagicMock()
    channel = FeishuChannel(config, bus)
    channel._client = MagicMock()
    return channel


def _get_tool_hint_card(mock_send):
    """Extract the interactive card from _send_message_sync calls."""
    call_args = mock_send.call_args[0]
    _, _, msg_type, content = call_args
    assert msg_type == "interactive"
    return json.loads(content)


@mark.asyncio
async def test_tool_hint_sends_interactive_card(mock_feishu_channel):
    """Tool hint without active buffer sends an interactive card with 🔧 style."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='web_search("test query")',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        assert mock_send.call_count == 1
        card = _get_tool_hint_card(mock_send)
        assert card["config"]["wide_screen_mode"] is True
        md = card["elements"][0]["content"]
        assert "\U0001f527" in md
        assert "web_search" in md


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

        assert mock_send.call_count == 1
        call_args = mock_send.call_args[0]
        _, _, msg_type, content = call_args
        assert msg_type == "text"
        assert json.loads(content) == {"text": "Hello, world!"}


@mark.asyncio
async def test_tool_hint_multiple_tools_in_one_message(mock_feishu_channel):
    """Multiple tool calls should each get the 🔧 prefix."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='web_search("query"), read_file("/path/to/file")',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        card = _get_tool_hint_card(mock_send)
        md = card["elements"][0]["content"]
        assert "web_search" in md
        assert "read_file" in md
        assert "\U0001f527" in md


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

        card = _get_tool_hint_card(mock_send)
        md = card["elements"][0]["content"]
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

        card = _get_tool_hint_card(mock_send)
        md = card["elements"][0]["content"]
        assert 'grep "hello, world"' in md
        assert "$ echo test" in md


@mark.asyncio
async def test_tool_hint_new_format_with_folding(mock_feishu_channel):
    """Folded calls (× N) should display correctly."""
    msg = OutboundMessage(
        channel="feishu",
        chat_id="oc_123456",
        content='read path × 3, grep "pattern"',
        metadata={"_tool_hint": True}
    )

    with patch.object(mock_feishu_channel, '_send_message_sync') as mock_send:
        await mock_feishu_channel.send(msg)

        card = _get_tool_hint_card(mock_send)
        md = card["elements"][0]["content"]
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

        card = _get_tool_hint_card(mock_send)
        md = card["elements"][0]["content"]
        assert "4_5v::analyze_image" in md


@mark.asyncio
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

        card = _get_tool_hint_card(mock_send)
        md = card["elements"][0]["content"]
        assert 'web_search("foo, bar")' in md
        assert 'read_file("/path/to/file")' in md
