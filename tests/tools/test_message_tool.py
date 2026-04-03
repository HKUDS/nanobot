from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: No target channel/chat specified"


@pytest.mark.asyncio
async def test_message_tool_keeps_default_message_id_for_same_target() -> None:
    sent: list[OutboundMessage] = []
    tool = MessageTool(send_callback=AsyncMock(side_effect=lambda m: sent.append(m)))
    tool.set_context("feishu", "chat-a", "msg-1")

    result = await tool.execute(content="hello")

    assert result == "Message sent to feishu:chat-a"
    assert sent[0].metadata["message_id"] == "msg-1"


@pytest.mark.asyncio
async def test_message_tool_drops_default_message_id_for_different_chat() -> None:
    sent: list[OutboundMessage] = []
    tool = MessageTool(send_callback=AsyncMock(side_effect=lambda m: sent.append(m)))
    tool.set_context("feishu", "chat-a", "msg-1")

    result = await tool.execute(content="hello", chat_id="chat-b")

    assert result == "Message sent to feishu:chat-b"
    assert sent[0].metadata == {}


@pytest.mark.asyncio
async def test_message_tool_drops_default_message_id_for_different_channel() -> None:
    sent: list[OutboundMessage] = []
    tool = MessageTool(send_callback=AsyncMock(side_effect=lambda m: sent.append(m)))
    tool.set_context("feishu", "chat-a", "msg-1")

    result = await tool.execute(content="hello", channel="discord", chat_id="chat-a")

    assert result == "Message sent to discord:chat-a"
    assert sent[0].metadata == {}


@pytest.mark.asyncio
async def test_message_tool_preserves_explicit_message_id_for_different_target() -> None:
    sent: list[OutboundMessage] = []
    tool = MessageTool(send_callback=AsyncMock(side_effect=lambda m: sent.append(m)))
    tool.set_context("feishu", "chat-a", "msg-1")

    result = await tool.execute(content="hello", chat_id="chat-b", message_id="msg-2")

    assert result == "Message sent to feishu:chat-b"
    assert sent[0].metadata["message_id"] == "msg-2"
