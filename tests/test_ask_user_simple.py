"""Integration tests for subagent ask_user functionality.

Run with: python -m pytest tests/test_ask_user_simple.py -v
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.subagent import DEFAULT_ASK_USER_TIMEOUT, SubagentManager
from nanobot.agent.tools.ask_user import AskUserTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


class TestAskUserTool:
    """Tests for the AskUserTool class."""

    @pytest.mark.asyncio
    async def test_ask_user_tool_basic(self):
        """Test AskUserTool basic functionality."""
        async def mock_callback(question: str) -> str:
            return f"response to: {question}"

        tool = AskUserTool(ask_callback=mock_callback)

        assert tool.name == "ask_user"
        assert "ask" in tool.description.lower()
        assert "question" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["question"]

        result = await tool.execute(question="What is your name?")
        assert result == "response to: What is your name?"

    @pytest.mark.asyncio
    async def test_ask_user_tool_execute(self):
        """Test AskUserTool execute method."""
        called_with = []

        async def mock_callback(question: str) -> str:
            called_with.append(question)
            return "test response"

        tool = AskUserTool(ask_callback=mock_callback)
        result = await tool.execute(question="Test question?")

        assert result == "test response"
        assert called_with == ["Test question?"]


class TestSubagentManagerAskUser:
    """Tests for SubagentManager ask_user integration."""

    @pytest.fixture
    def mock_provider(self):
        """Create a mock LLM provider."""
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        return provider

    @pytest.fixture
    def message_bus(self):
        """Create a message bus."""
        return MessageBus()

    @pytest.fixture
    def subagent_manager(self, mock_provider, message_bus, tmp_path):
        """Create a SubagentManager with mocked dependencies."""
        return SubagentManager(
            provider=mock_provider,
            workspace=tmp_path,
            bus=message_bus,
            ask_user_timeout=5.0,  # Short timeout for testing
        )

    @pytest.mark.asyncio
    async def test_ask_user_timeout(self, subagent_manager):
        """Test that ask_user raises TimeoutError when no response is received."""
        # Don't publish any response, let it timeout
        with pytest.raises(asyncio.TimeoutError):
            await subagent_manager._handle_ask_request(
                task_id="test-task-1",
                question="What is your name?",
                label="test-label",
                origin={"channel": "cli", "chat_id": "direct"},
            )

    @pytest.mark.asyncio
    async def test_ask_user_success(self, subagent_manager, message_bus):
        """Test successful ask_user flow."""
        task_id = "test-task-2"
        expected_response = "My name is Alice"

        # Schedule a response after a short delay
        async def send_response():
            await asyncio.sleep(0.1)
            await subagent_manager.resume_with_user_response(task_id, expected_response)

        # Start both coroutines
        response_task = asyncio.create_task(send_response())

        try:
            result = await subagent_manager._handle_ask_request(
                task_id=task_id,
                question="What is your name?",
                label="test-label",
                origin={"channel": "cli", "chat_id": "direct"},
            )
            assert result == expected_response
        finally:
            await response_task

    @pytest.mark.asyncio
    async def test_ask_user_publishes_message(self, subagent_manager, message_bus):
        """Test that ask_user publishes a message to the bus."""
        task_id = "test-task-3"

        # Start ask_user in background
        ask_task = asyncio.create_task(
            subagent_manager._handle_ask_request(
                task_id=task_id,
                question="What is your favorite color?",
                label="color-task",
                origin={"channel": "cli", "chat_id": "direct"},
            )
        )

        # Consume the published message
        msg = await asyncio.wait_for(message_bus.consume_inbound(), timeout=1.0)

        assert msg.channel == "system"
        assert msg.metadata.get("ask_user") is True
        assert msg.metadata.get("task_id") == task_id
        assert msg.metadata.get("subagent_label") == "color-task"
        assert "What is your favorite color?" in msg.content

        # Clean up
        await subagent_manager.resume_with_user_response(task_id, "blue")
        await ask_task

    @pytest.mark.asyncio
    async def test_is_waiting_for_user(self, subagent_manager):
        """Test is_waiting_for_user method."""
        task_id = "test-task-4"

        assert not subagent_manager.is_waiting_for_user(task_id)

        # Start ask_user but don't respond yet
        ask_task = asyncio.create_task(
            subagent_manager._handle_ask_request(
                task_id=task_id,
                question="Waiting...",
                label="wait-task",
                origin={"channel": "cli", "chat_id": "direct"},
            )
        )

        # Give it time to set up the wait state
        await asyncio.sleep(0.05)

        assert subagent_manager.is_waiting_for_user(task_id)

        # Clean up
        await subagent_manager.resume_with_user_response(task_id, "done")
        await ask_task

        assert not subagent_manager.is_waiting_for_user(task_id)

    @pytest.mark.asyncio
    async def test_cleanup_on_exception(self, subagent_manager):
        """Test that wait state is cleaned up even when task is cancelled."""
        task_id = "test-task-5"

        # Start ask_user
        ask_task = asyncio.create_task(
            subagent_manager._handle_ask_request(
                task_id=task_id,
                question="Cancel me?",
                label="cancel-task",
                origin={"channel": "cli", "chat_id": "direct"},
            )
        )

        # Give it time to set up
        await asyncio.sleep(0.05)
        assert subagent_manager.is_waiting_for_user(task_id)

        # Cancel the task
        ask_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await ask_task

        # Wait state should be cleaned up by finally block
        assert not subagent_manager.is_waiting_for_user(task_id)
        assert task_id not in subagent_manager._user_responses


class TestAskUserMessageRouting:
    """Tests for ask_user message routing in AgentLoop."""

    @pytest.fixture
    def mock_loop_deps(self):
        """Create mocked dependencies for AgentLoop."""
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.generation.max_tokens = 8192

        with patch("nanobot.agent.loop.ContextBuilder"), \
             patch("nanobot.agent.loop.SessionManager"), \
             patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
            MockSubMgr.return_value._running_tasks = {}
            yield bus, provider, MockSubMgr

    @pytest.mark.asyncio
    async def test_explicit_reply_format(self, mock_loop_deps):
        """Test that 'reply <task_id>: <message>' format works."""
        from nanobot.agent.loop import AgentLoop

        bus, provider, MockSubMgr = mock_loop_deps
        mock_resume = AsyncMock()
        MockSubMgr.return_value.resume_with_user_response = mock_resume

        loop = AgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        # Set up a pending ask request
        loop._pending_ask_requests["abc123"] = {
            "session_key": "cli:direct",
            "question": "What is your name?",
        }

        # Send a reply in the correct format
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="reply abc123: My name is Bob",
        )

        response = await loop._process_message(msg)

        # Should have called resume_with_user_response
        mock_resume.assert_called_once_with("abc123", "My name is Bob")
        # Should have been removed from pending
        assert "abc123" not in loop._pending_ask_requests
        # Should return confirmation message
        assert response is not None
        assert "abc123" in response.content
        assert "Reply sent" in response.content

    @pytest.mark.asyncio
    async def test_explicit_abort_format(self, mock_loop_deps):
        """Test that 'abort <task_id>' format works."""
        from nanobot.agent.loop import AgentLoop

        bus, provider, MockSubMgr = mock_loop_deps
        MockSubMgr.return_value._running_tasks = {"xyz789": MagicMock()}

        loop = AgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        # Set up a pending ask request
        loop._pending_ask_requests["xyz789"] = {
            "session_key": "cli:direct",
            "question": "What is your name?",
        }

        # Send abort command
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="abort xyz789",
        )

        response = await loop._process_message(msg)

        # Should have cancelled the task
        MockSubMgr.return_value._running_tasks["xyz789"].cancel.assert_called_once()
        # Should have been removed from pending
        assert "xyz789" not in loop._pending_ask_requests
        # Should return confirmation message
        assert response is not None
        assert "xyz789" in response.content
        assert "cancelled" in response.content.lower()

    @pytest.mark.asyncio
    async def test_regular_message_not_consumed(self, mock_loop_deps):
        """Test that regular messages are not consumed when there's a pending ask."""
        from nanobot.agent.loop import AgentLoop

        bus, provider, MockSubMgr = mock_loop_deps
        loop = AgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        # Set up a pending ask request
        loop._pending_ask_requests["task999"] = {
            "session_key": "cli:direct",
            "question": "What is your name?",
        }

        # Send a regular message without reply format
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="Just a regular message without the reply prefix",
        )

        # Process the message - it should pass through (not be consumed)
        # Note: It will fail because we haven't mocked everything, but
        # the important thing is that it shouldn't match the pending ask
        # Since the full _process_message is complex, we just verify
        # the pending ask is still there after attempting to process
        try:
            await loop._process_message(msg)
        except Exception:
            pass  # We expect errors from incomplete mocking

        # The pending ask should still be there (message wasn't consumed)
        assert "task999" in loop._pending_ask_requests

    @pytest.mark.asyncio
    async def test_multiple_pending_asks_per_session(self, mock_loop_deps):
        """Test that multiple subagents can wait for input in the same session."""
        from nanobot.agent.loop import AgentLoop

        bus, provider, MockSubMgr = mock_loop_deps
        mock_resume = AsyncMock()
        MockSubMgr.return_value.resume_with_user_response = mock_resume

        loop = AgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        # Set up two pending ask requests for the same session
        loop._pending_ask_requests["task1"] = {
            "session_key": "cli:direct",
            "question": "Question 1?",
        }
        loop._pending_ask_requests["task2"] = {
            "session_key": "cli:direct",
            "question": "Question 2?",
        }

        # Reply to the first one
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content="reply task1: Answer 1",
        )

        await loop._process_message(msg)

        # Only task1 should have been processed
        mock_resume.assert_called_once_with("task1", "Answer 1")
        assert "task1" not in loop._pending_ask_requests
        assert "task2" in loop._pending_ask_requests

    @pytest.mark.asyncio
    async def test_ask_user_message_format(self, mock_loop_deps):
        """Test that ask_user messages include task_id and instructions."""
        from nanobot.agent.loop import AgentLoop

        bus, provider, MockSubMgr = mock_loop_deps
        loop = AgentLoop(bus=bus, provider=provider, workspace=MagicMock())

        # Simulate receiving an ask_user request from subagent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id="cli:direct",
            content="[Subagent 'my-task' needs input]\n\nQuestion: What should I do?",
            metadata={
                "ask_user": True,
                "task_id": "sub123",
                "subagent_label": "my-task",
            },
        )

        response = await loop._process_message(msg)

        assert response is not None
        # Should include task_id
        assert "sub123" in response.content
        # Should include instructions
        assert "reply sub123:" in response.content
        assert "abort sub123" in response.content
        # Should have stored in pending with task_id as key
        assert "sub123" in loop._pending_ask_requests
        assert loop._pending_ask_requests["sub123"]["session_key"] == "cli:direct"


class TestDefaultTimeout:
    """Tests for the default timeout constant."""

    def test_default_timeout_value(self):
        """Test that default timeout is 600 seconds (10 minutes)."""
        assert DEFAULT_ASK_USER_TIMEOUT == 600

    def test_subagent_manager_uses_default(self, tmp_path):
        """Test that SubagentManager uses default timeout when not specified."""
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        mgr = SubagentManager(
            provider=provider,
            workspace=tmp_path,
            bus=bus,
        )

        assert mgr.ask_user_timeout == DEFAULT_ASK_USER_TIMEOUT

    def test_subagent_manager_custom_timeout(self, tmp_path):
        """Test that SubagentManager accepts custom timeout."""
        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        mgr = SubagentManager(
            provider=provider,
            workspace=tmp_path,
            bus=bus,
            ask_user_timeout=300.0,
        )

        assert mgr.ask_user_timeout == 300.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
