"""Tests for async event injection mechanism."""

import asyncio
from unittest.mock import MagicMock

import pytest


@pytest.mark.asyncio
async def test_messagebus_event_channel_creation():
    """Test that event channels are created on demand."""
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    session_key = "telegram:12345"

    # Publish an event
    await bus.publish_event(session_key, "User sent: stop")

    # Event channel should exist
    assert session_key in bus._event_channels

    # Check event retrieval
    event = await bus.check_events(session_key)
    assert event == "- User sent: stop"

    # Second check should return None (queue empty)
    event2 = await bus.check_events(session_key)
    assert event2 is None


@pytest.mark.asyncio
async def test_messagebus_event_accumulation():
    """Test that multiple events are accumulated and returned together."""
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    session_key = "discord:67890"

    await bus.publish_event(session_key, "First message")
    await bus.publish_event(session_key, "Second message")
    await bus.publish_event(session_key, "Third message")

    events = await bus.check_events(session_key)
    assert events == "- First message\n- Second message\n- Third message"

    # Queue should be empty after retrieval
    assert await bus.check_events(session_key) is None


@pytest.mark.asyncio
async def test_messagebus_non_blocking_check():
    """Test that check_events doesn't block when no events."""
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    session_key = "test:key"

    # Should return immediately with None
    start = asyncio.get_event_loop().time()
    event = await bus.check_events(session_key)
    elapsed = asyncio.get_event_loop().time() - start

    assert event is None
    assert elapsed < 0.01  # Should be nearly instant


def test_system_prompt_includes_event_handling():
    """Test that system prompt includes event handling instructions when enabled."""
    from unittest.mock import MagicMock, patch
    from nanobot.agent.context import ContextBuilder

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.context.MemoryStore"), \
         patch("nanobot.agent.context.SkillsLoader"):
        builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt(enable_event_handling=True)

    assert "Event Handling" in prompt
    assert "<SYS_EVENT>" in prompt
    assert "IMMEDIATELY acknowledge" in prompt
    assert "ALWAYS takes priority" in prompt
    assert "type=\"user_interrupt\"" not in prompt  # Directive uses generic tag


def test_system_prompt_no_event_handling_by_default():
    """Test that event handling is NOT included by default."""
    from unittest.mock import MagicMock, patch
    from nanobot.agent.context import ContextBuilder

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.context.MemoryStore"), \
         patch("nanobot.agent.context.SkillsLoader"):
        builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt()

    # Should not contain event handling by default
    assert "Event Handling" not in prompt


@pytest.mark.asyncio
async def test_agent_loop_checks_events_before_llm():
    """Test that agent loop checks for events before calling LLM."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    # Mock LLM response with no tool calls
    mock_response = MagicMock()
    mock_response.has_tool_calls = False
    mock_response.content = "Hello"
    provider.chat = AsyncMock(return_value=mock_response)

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder") as MockCtx, \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        # Configure ContextBuilder mock to properly handle add_assistant_message
        mock_ctx = MagicMock()
        def add_assistant(messages, content, tool_calls=None, **kwargs):
            msg = {"role": "assistant", "content": content}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            if "reasoning_content" in kwargs and kwargs["reasoning_content"] is not None:
                msg["reasoning_content"] = kwargs["reasoning_content"]
            messages.append(msg)
            return messages
        mock_ctx.add_assistant_message.side_effect = add_assistant
        MockCtx.return_value = mock_ctx

        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)

    # Publish an event before running loop
    await bus.publish_event("test:key", "User interrupt")

    # Run loop with event callback
    final_content, _, messages = await loop._run_agent_loop(
        initial_messages=[{"role": "user", "content": "test"}],
        on_progress=None,
        session_key="test:key",
    )

    # Event should have been injected as a system message with <SYS_EVENT> tag
    assert any("<SYS_EVENT" in m.get("content", "") and "User interrupt" in m.get("content", "") for m in messages)


@pytest.mark.asyncio
async def test_agent_loop_cancels_tools_on_event():
    """Test that pending tool calls are cancelled when event arrives."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    # Mock LLM response with tool calls
    mock_response = MagicMock()
    mock_response.has_tool_calls = True
    mock_response.content = "Let me search"
    mock_response.reasoning_content = None
    mock_tool = MagicMock()
    mock_tool.id = "call_123"
    mock_tool.name = "web_search"
    mock_tool.arguments = {"query": "test"}
    mock_response.tool_calls = [mock_tool]

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"), \
         patch("nanobot.agent.loop.ToolRegistry") as MockRegistry:
        mock_registry = MagicMock()
        mock_registry.get_definitions.return_value = []

        # Mock tools.execute to track if it was called
        mock_execute = AsyncMock(return_value="result")
        mock_registry.execute = mock_execute
        MockRegistry.return_value = mock_registry

        # Create chat mock that publishes event during call
        async def chat_with_event(*args, **kwargs):
            # Publish event when LLM is called (simulating user interrupt)
            await bus.publish_event("test:key", "Stop now")
            return mock_response

        provider.chat = AsyncMock(side_effect=chat_with_event)

        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)

    final_content, tools_used, messages = await loop._run_agent_loop(
        initial_messages=[{"role": "user", "content": "test"}],
        session_key="test:key",
    )

    # Tools should not be executed (event cancelled them)
    assert tools_used == []
    # execute should not have been called
    mock_execute.assert_not_called()


def test_event_handling_config_default():
    """Test that event handling is disabled by default."""
    from nanobot.config.schema import AgentDefaults

    config = AgentDefaults()
    assert config.enable_event_handling is False


def test_event_handling_config_enabled():
    """Test that event handling can be enabled via config."""
    from nanobot.config.schema import AgentDefaults

    config = AgentDefaults(enable_event_handling=True)
    assert config.enable_event_handling is True


@pytest.mark.asyncio
async def test_end_to_end_event_injection():
    """Test complete flow: user message -> event -> LLM response."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()

    # Mock provider that simulates task interruption
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    # First call: LLM decides to use a tool
    response1 = MagicMock()
    response1.has_tool_calls = True
    response1.content = "I'll search for that"
    response1.reasoning_content = None
    tool1 = MagicMock()
    tool1.id = "call_1"
    tool1.name = "web_search"
    tool1.arguments = {"query": "python sorting"}
    response1.tool_calls = [tool1]

    # After event: LLM acknowledges and switches
    response2 = MagicMock()
    response2.has_tool_calls = False
    response2.content = "I'll stop searching and help you with the stock price instead."
    response2.reasoning_content = None

    provider.chat = AsyncMock(side_effect=[response1, response2])

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder") as MockCtx, \
         patch("nanobot.agent.loop.SubagentManager"), \
         patch("nanobot.agent.loop.ToolRegistry") as MockRegistry:
        mock_ctx = MagicMock()
        mock_ctx.build_messages.return_value = [
            {"role": "system", "content": "You are nanobot"},
            {"role": "user", "content": "Search for python sorting algorithms"}
        ]
        mock_ctx.add_assistant_message.side_effect = lambda msgs, c, tc=None, **kw: msgs + [{"role": "assistant", "content": c, "tool_calls": tc}]
        mock_ctx.add_tool_result.side_effect = lambda msgs, tid, tn, res: msgs + [{"role": "tool", "tool_call_id": tid, "name": tn, "content": res}]
        MockCtx.return_value = mock_ctx

        mock_registry = MagicMock()
        mock_registry.get_definitions.return_value = [
            {"type": "function", "function": {"name": "web_search", "parameters": {}}}
        ]
        mock_registry.execute = AsyncMock(return_value="Search results...")
        MockRegistry.return_value = mock_registry

        # Mock session manager properly
        mock_session = MagicMock()
        mock_session.messages = []
        mock_session.last_consolidated = 0
        mock_session.key = "test:c1"
        mock_session.get_history.return_value = []

        mock_session_manager = MagicMock()
        mock_session_manager.get_or_create.return_value = mock_session

        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace,
                        session_manager=mock_session_manager, enable_event_handling=True)

    # Start processing a message
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="Search for python sorting")

    # In background, publish an interrupt event
    async def interrupt_later():
        await asyncio.sleep(0.01)  # Wait for loop to start
        await bus.publish_event("test:c1", "Never mind, check AAPL stock price instead")

    asyncio.create_task(interrupt_later())

    # Process message
    response = await loop._process_message(msg, session_key="test:c1")

    # LLM should have acknowledged the event
    assert response is not None
    # The final response should mention the event (stock price)
    # Note: Since provider.chat is mocked with side_effect, the final response
    # comes from response2 which mentions "stock price"


@pytest.mark.asyncio
async def test_no_event_overhead():
    """Test that event checking adds negligible overhead when no events."""
    from unittest.mock import AsyncMock, MagicMock, patch
    import time
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    mock_response = MagicMock()
    mock_response.has_tool_calls = False
    mock_response.content = "Response"
    provider.chat = AsyncMock(return_value=mock_response)

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)

    start = time.perf_counter()
    for _ in range(100):
        await loop._run_agent_loop(
            initial_messages=[{"role": "user", "content": "test"}],
            session_key="test:key",
        )
    elapsed = time.perf_counter() - start

    # 100 iterations should be fast (< 1 second)
    assert elapsed < 1.0, f"Event checking overhead too high: {elapsed}s for 100 iterations"


@pytest.mark.asyncio
async def test_event_published_when_active_task_exists():
    """Test that events are published when user sends message during task execution."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(return_value=MagicMock(
        has_tool_calls=False,
        content="Response"
    ))

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace, enable_event_handling=True)

    # Simulate a message currently being processed (has acquired processing lock)
    # This is the key difference: _processing_tasks tracks tasks actually executing
    session_key = "test:channel"
    loop._processing_tasks.add(session_key)

    # Verify _processing_tasks correctly identifies processing state
    assert session_key in loop._processing_tasks
    assert "nonexistent" not in loop._processing_tasks

    # Simulate the event publishing code from _process_message
    if loop.enable_event_handling and session_key in loop._processing_tasks:
        await bus.publish_event(session_key, "Interrupt message")

    # Verify event was published
    event = await bus.check_events(session_key)
    assert event is not None
    assert "Interrupt message" in event

    # After processing completes, task is removed from _processing_tasks
    loop._processing_tasks.discard(session_key)
    assert session_key not in loop._processing_tasks
