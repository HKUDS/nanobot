"""Test that _process_message returns OutboundMessage with correct fields."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import SessionManager


class MockLLMProvider(LLMProvider):
    """Mock LLM provider that returns simple responses."""

    async def chat(self, messages, tools=None, model=None, temperature=0.7, max_tokens=4096):
        return LLMResponse(
            content="Test response",
            reasoning_content="Test reasoning",
            tool_calls=[],
        )

    def get_default_model(self) -> str:
        return "test-model"


async def test_process_message_returns_outbound_message() -> None:
    """Verify _process_message returns OutboundMessage with all fields."""
    # Setup
    bus = MessageBus()
    provider = MockLLMProvider(api_key="test")
    workspace = Path("/tmp/test_workspace")
    workspace.mkdir(parents=True, exist_ok=True)

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model="test-model",
    )

    # Create inbound message
    msg = InboundMessage(
        channel="cli",
        sender_id="test_user",
        chat_id="test_chat",
        content="Hello",
    )

    # Process message
    response = await agent_loop._process_message(msg)

    # Verify response is OutboundMessage
    assert isinstance(response, OutboundMessage), f"Expected OutboundMessage, got {type(response)}"

    # Verify required fields
    assert response.channel == "cli", f"Expected channel='cli', got {response.channel}"
    assert response.chat_id == "test_chat", f"Expected chat_id='test_chat', got {response.chat_id}"
    assert response.content == "Test response", f"Expected content='Test response', got {response.content}"
    assert response.reasoning_content == "Test reasoning", f"Expected reasoning_content='Test reasoning', got {response.reasoning_content}"

    # Cleanup
    import shutil
    shutil.rmtree(workspace, ignore_errors=True)


async def test_process_message_with_none_content() -> None:
    """Verify _process_message handles None content gracefully."""
    # Setup
    bus = MessageBus()

    class MockEmptyProvider(LLMProvider):
        async def chat(self, messages, tools=None, model=None, temperature=0.7, max_tokens=4096):
            return LLMResponse(
                content=None,
                reasoning_content="Some reasoning",
                tool_calls=[],
            )

        def get_default_model(self) -> str:
            return "test-model"

    provider = MockEmptyProvider(api_key="test")
    workspace = Path("/tmp/test_workspace_none")
    workspace.mkdir(parents=True, exist_ok=True)

    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model="test-model",
    )

    # Create inbound message
    msg = InboundMessage(
        channel="cli",
        sender_id="test_user",
        chat_id="test_chat",
        content="Hello",
    )

    # Process message
    response = await agent_loop._process_message(msg)

    # Verify response uses fallback message
    assert isinstance(response, OutboundMessage), f"Expected OutboundMessage, got {type(response)}"
    assert response.content == "I've completed processing but have no response to give.", \
        f"Expected fallback message, got {response.content}"

    # Cleanup
    import shutil
    shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
