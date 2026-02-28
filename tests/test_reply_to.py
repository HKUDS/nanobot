"""Tests for reply_to parameter in message tool."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.tools.message import MessageTool
from nanobot.agent.context import ContextBuilder
from nanobot.bus.events import OutboundMessage


class TestReplyToMetadata:
    """Tests for reply_to_message_id in metadata (receiving replies)."""
    
    def test_runtime_context_shows_reply_to(self):
        """Runtime context should show reply_to_message_id when present."""
        metadata = {"reply_to_message_id": 12345}
        ctx = ContextBuilder._build_runtime_context("telegram", "123", metadata)
        
        assert "Reply to message: 12345" in ctx
    
    def test_runtime_context_without_reply_to(self):
        """Runtime context should work without reply_to_message_id."""
        metadata = {"user_id": 999}
        ctx = ContextBuilder._build_runtime_context("telegram", "123", metadata)
        
        assert "Reply to message" not in ctx
    
    def test_runtime_context_none_metadata(self):
        """Runtime context should handle None metadata."""
        ctx = ContextBuilder._build_runtime_context("telegram", "123", None)
        
        assert "Reply to message" not in ctx


class TestReplyToParameter:
    """Tests for reply_to parameter functionality."""
    
    @pytest.mark.asyncio
    async def test_message_tool_accepts_reply_to(self):
        """MessageTool should accept reply_to parameter."""
        mock_callback = AsyncMock(return_value="123")
        tool = MessageTool(send_callback=mock_callback)
        
        result = await tool.execute(
            content="Test reply",
            channel="telegram",
            chat_id="12345",
            reply_to="999"
        )
        
        # Check callback was called with correct OutboundMessage
        call_args = mock_callback.call_args[0][0]
        assert isinstance(call_args, OutboundMessage)
        assert call_args.reply_to == "999"
        assert "reply to 999" in result
    
    @pytest.mark.asyncio
    async def test_message_tool_returns_message_id(self):
        """MessageTool should return message_id from callback."""
        mock_callback = AsyncMock(return_value="456")
        tool = MessageTool(send_callback=mock_callback)
        
        result = await tool.execute(
            content="Test message",
            channel="telegram",
            chat_id="12345"
        )
        
        assert "[id=456]" in result
    
    @pytest.mark.asyncio
    async def test_message_tool_without_reply_to(self):
        """MessageTool should work without reply_to parameter."""
        mock_callback = AsyncMock(return_value=None)
        tool = MessageTool(send_callback=mock_callback)
        
        result = await tool.execute(
            content="Test message",
            channel="telegram",
            chat_id="12345"
        )
        
        # Check OutboundMessage has reply_to=None
        call_args = mock_callback.call_args[0][0]
        assert call_args.reply_to is None
        assert "reply to" not in result
