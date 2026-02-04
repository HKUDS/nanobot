import pytest
from unittest.mock import MagicMock, AsyncMock
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from pathlib import Path

@pytest.mark.asyncio
async def test_agent_loop_handles_empty_response():
    # Mock dependencies
    bus = MagicMock(spec=MessageBus)
    provider = MagicMock(spec=LLMProvider)
    workspace = Path("/tmp/nanobot_test")
    workspace.mkdir(parents=True, exist_ok=True)
    
    # Mock LLM response with empty content
    mock_response = LLMResponse(content="", tool_calls=[])
    provider.chat = AsyncMock(return_value=mock_response)
    provider.get_default_model.return_value = "test-model"
    
    loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    
    # Inbound message
    msg = InboundMessage(
        channel="test",
        sender_id="user",
        chat_id="123",
        content="hello"
    )
    
    # Process message
    response = await loop._process_message(msg)
    
    # Verify response content is the default message, not empty string
    assert response.content == "I've completed processing but have no response to give."

@pytest.mark.asyncio
async def test_telegram_channel_skips_empty_message():
    from nanobot.channels.telegram import TelegramChannel
    from nanobot.config.schema import TelegramConfig
    
    bus = MagicMock(spec=MessageBus)
    config = TelegramConfig(token="fake-token")
    channel = TelegramChannel(config=config, bus=bus)
    
    # Mock the telegram application and bot
    channel._app = MagicMock()
    channel._app.bot.send_message = AsyncMock()
    
    # Outbound message with empty content
    msg = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content=""
    )
    
    # Send message
    await channel.send(msg)
    
    # Verify send_message was NOT called
    channel._app.bot.send_message.assert_not_called()

    # Outbound message with whitespace content
    msg_ws = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content="   "
    )
    
    # Send message
    await channel.send(msg_ws)
    
    # Verify send_message was NOT called
    channel._app.bot.send_message.assert_not_called()
