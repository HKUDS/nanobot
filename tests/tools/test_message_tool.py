import pytest
from unittest.mock import AsyncMock

from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import OutboundMessage


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    tool = MessageTool()
    result = await tool.execute(content="test")
    assert result == "Error: No target channel/chat specified"


@pytest.mark.asyncio
async def test_message_tool_preserves_context_metadata() -> None:
    sent: list[OutboundMessage] = []
    tool = MessageTool(send_callback=AsyncMock(side_effect=lambda msg: sent.append(msg)))

    tool.set_context("telegram", "123", "10", {"message_id": 10, "message_thread_id": 42})

    result = await tool.execute(content="hello")

    assert result == "Message sent to telegram:123"
    assert sent[0].metadata == {"message_id": "10", "message_thread_id": 42}


@pytest.mark.asyncio
async def test_message_tool_keeps_context_metadata_when_overriding_message_id() -> None:
    sent: list[OutboundMessage] = []
    tool = MessageTool(send_callback=AsyncMock(side_effect=lambda msg: sent.append(msg)))

    tool.set_context("telegram", "123", "10", {"message_id": 10, "message_thread_id": 42})

    result = await tool.execute(content="hello", message_id="11")

    assert result == "Message sent to telegram:123"
    assert sent[0].metadata == {"message_id": "11", "message_thread_id": 42}
