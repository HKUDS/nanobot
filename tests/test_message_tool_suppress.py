"""Test message tool suppress logic for final replies (ADK-based)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.adk.tools import send_message, set_runtime_refs


class TestSendMessageTool:
    """Test the ADK send_message function tool."""

    @pytest.mark.asyncio
    async def test_send_message_sets_sent_in_turn(self) -> None:
        """send_message should set temp:sent_in_turn when sending to originating channel."""
        callback = AsyncMock()
        set_runtime_refs(bus_publish=callback)

        ctx = MagicMock()
        ctx.state = {
            "temp:channel": "telegram",
            "temp:chat_id": "chat123",
            "temp:message_id": "",
            "temp:sent_in_turn": "false",
        }

        result = await send_message(
            content="Hello",
            channel="telegram",
            chat_id="chat123",
            tool_context=ctx,
        )

        assert "Message sent" in result
        assert ctx.state["temp:sent_in_turn"] == "true"
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_to_different_target_no_suppress(self) -> None:
        """send_message to a different channel should NOT set sent_in_turn."""
        callback = AsyncMock()
        set_runtime_refs(bus_publish=callback)

        ctx = MagicMock()
        ctx.state = {
            "temp:channel": "telegram",
            "temp:chat_id": "chat123",
            "temp:message_id": "",
            "temp:sent_in_turn": "false",
        }

        result = await send_message(
            content="Email content",
            channel="email",
            chat_id="user@example.com",
            tool_context=ctx,
        )

        assert "Message sent" in result
        assert ctx.state["temp:sent_in_turn"] == "false"

    @pytest.mark.asyncio
    async def test_send_message_no_callback_returns_error(self) -> None:
        """send_message without bus callback should return error."""
        import nanobot.adk.tools as tools_mod
        tools_mod._bus_callback = None

        ctx = MagicMock()
        ctx.state = {
            "temp:channel": "telegram",
            "temp:chat_id": "chat123",
            "temp:message_id": "",
            "temp:sent_in_turn": "false",
        }

        result = await send_message(content="Hello", tool_context=ctx)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_send_message_uses_defaults_from_context(self) -> None:
        """send_message with no explicit channel should use context defaults."""
        callback = AsyncMock()
        set_runtime_refs(bus_publish=callback)

        ctx = MagicMock()
        ctx.state = {
            "temp:channel": "discord",
            "temp:chat_id": "server1",
            "temp:message_id": "msg42",
            "temp:sent_in_turn": "false",
        }

        result = await send_message(content="Hi", tool_context=ctx)
        assert "Message sent to discord:server1" in result
        assert ctx.state["temp:sent_in_turn"] == "true"
