"""Tests for agent loop message history preservation.

This tests the fix for issue #1236 where assistant messages were not being
saved to history when there were no tool calls.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_assistant_message_saved_without_tool_calls():
    """Test that assistant message is saved to history even without tool calls."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import LLMResponse

    # Mock the provider to return a simple text response (no tool calls)
    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="Hello! I'm nanobot.",
            tool_calls=[],
            finish_reason="stop",
        )
    )

    # Create a mock workspace and dependencies
    workspace = MagicMock(spec=Path)
    workspace.__truediv__ = MagicMock(return_value=MagicMock(spec=Path))

    with patch("nanobot.agent.loop.MemoryStore"), \
         patch("nanobot.agent.loop.ToolRegistry"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=mock_provider,
            model="test-model",
            workspace=workspace,
        )

    # Initial messages (system + user)
    initial_messages = [
        {"role": "system", "content": "You are nanobot"},
        {"role": "user", "content": "Hello"},
    ]

    # Run the agent loop
    final_content, _, all_messages = await loop._run_agent_loop(initial_messages)

    # Assertions
    assert final_content == "Hello! I'm nanobot."

    # The key assertion: assistant message should be in the returned messages
    assistant_messages = [m for m in all_messages if m.get("role") == "assistant"]
    assert len(assistant_messages) == 1, "Assistant message should be added to history"
    assert assistant_messages[0]["content"] == "Hello! I'm nanobot."


@pytest.mark.asyncio
async def test_assistant_message_saved_with_tool_calls():
    """Test that assistant message with tool_calls is saved to history."""
    from nanobot.agent.context import ContextBuilder

    # Test the ContextBuilder.add_assistant_message directly
    # This tests the existing behavior that worked correctly
    builder = ContextBuilder(MagicMock(spec=Path))

    messages = [
        {"role": "system", "content": "You are nanobot"},
        {"role": "user", "content": "What time is it?"},
    ]

    # Add assistant message with tool_calls
    tool_call_dicts = [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "get_time",
                "arguments": "{}"
            }
        }
    ]

    updated_messages = builder.add_assistant_message(
        messages,
        "I'll check the time",
        tool_call_dicts,
        reasoning_content=None,
    )

    # Verify assistant message was added
    assistant_messages = [m for m in updated_messages if m.get("role") == "assistant"]
    assert len(assistant_messages) == 1, "Assistant message with tool_calls should be in history"
    assert "tool_calls" in assistant_messages[0]
    assert assistant_messages[0]["content"] == "I'll check the time"
    assert len(assistant_messages[0]["tool_calls"]) == 1


@pytest.mark.asyncio
async def test_assistant_message_preserved_after_save():
    """Test that assistant message is properly saved to session."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import LLMResponse

    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="My name is nanobot!",
            tool_calls=[],
            finish_reason="stop",
        )
    )

    workspace = MagicMock(spec=Path)
    workspace.__truediv__ = MagicMock(return_value=MagicMock(spec=Path))

    with patch("nanobot.agent.loop.MemoryStore"), \
         patch("nanobot.agent.loop.ToolRegistry"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=mock_provider,
            model="test-model",
            workspace=workspace,
        )

    initial_messages = [
        {"role": "system", "content": "You are nanobot"},
        {"role": "user", "content": "What is your name?"},
    ]

    # Run the loop
    _, _, all_messages = await loop._run_agent_loop(initial_messages)

    # Simulate saving (similar to _save_turn)
    # skip=1 to skip the system message
    new_messages = all_messages[1:]

    # Verify the assistant message is in the new messages to be saved
    assistant_messages = [m for m in new_messages if m.get("role") == "assistant"]
    assert len(assistant_messages) == 1, "Assistant message should be in save batch"
    assert assistant_messages[0]["content"] == "My name is nanobot!"


@pytest.mark.asyncio
async def test_assistant_message_with_reasoning_content():
    """Test that reasoning_content is properly handled in assistant messages."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import LLMResponse

    mock_provider = MagicMock()
    mock_provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="Final answer here",
            reasoning_content="Let me think about this...",
            tool_calls=[],
            finish_reason="stop",
        )
    )

    workspace = MagicMock(spec=Path)
    workspace.__truediv__ = MagicMock(return_value=MagicMock(spec=Path))

    with patch("nanobot.agent.loop.MemoryStore"), \
         patch("nanobot.agent.loop.ToolRegistry"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(
            bus=MessageBus(),
            provider=mock_provider,
            model="test-model",
            workspace=workspace,
        )

    initial_messages = [
        {"role": "system", "content": "You are nanobot"},
        {"role": "user", "content": "Question"},
    ]

    _, _, all_messages = await loop._run_agent_loop(initial_messages)

    # Find assistant message
    assistant_messages = [m for m in all_messages if m.get("role") == "assistant"]
    assert len(assistant_messages) == 1

    # reasoning_content should be in the message
    assert "reasoning_content" in assistant_messages[0]
    assert assistant_messages[0]["reasoning_content"] == "Let me think about this..."
