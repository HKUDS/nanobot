"""Unit tests for A2AChannel."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from a2a.types import Message, MessageSendParams, Part


@pytest.fixture
def mock_bus():
    """Create a mock message bus."""
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    bus.consume_outbound = AsyncMock()
    return bus


@pytest.fixture
def mock_config():
    """Create a mock A2A config with skill dicts (as they would be in YAML config)."""
    config = MagicMock()
    config.agent_name = "Test Agent"
    config.agent_url = "http://localhost:8000"
    config.agent_description = "Test description"
    config.skills = [
        {"id": "chat", "name": "Chat", "description": "General chat", "tags": []},
        {"id": "assist", "name": "Assist", "description": "Task assistance", "tags": []},
    ]
    return config


@pytest.fixture
def mock_session_manager():
    """Create a mock session manager."""
    return MagicMock()


@pytest.fixture
def a2a_channel(mock_config, mock_bus, mock_session_manager):
    """Create an A2A channel instance."""
    from nanobot.channels.a2a import A2AChannel, A2A_AVAILABLE
    if not A2A_AVAILABLE:
        pytest.skip("a2a-sdk not installed")
    return A2AChannel(mock_config, mock_bus, mock_session_manager)


def make_message(text: str, role: str = "user", context_id: str | None = None):
    """Helper to create A2A Message with required fields."""
    return Message(
        message_id=f"msg-{uuid.uuid4().hex[:8]}",
        role=role,
        parts=[Part(type="text", text=text)],
        context_id=context_id,
    )


class TestA2AChannelInit:
    """Tests for A2AChannel initialization."""

    def test_channel_name(self, a2a_channel):
        """Test channel name is 'a2a'."""
        assert a2a_channel.name == "a2a"

    def test_agent_card_created(self, a2a_channel):
        """Test agent card is created from config."""
        card = a2a_channel.agent_card
        assert card is not None
        assert card.name == "Test Agent"
        assert card.url == "http://localhost:8000"
        assert card.description == "Test description"
        assert len(card.skills) == 2

    def test_handler_initialized(self, a2a_channel):
        """Test request handler is initialized."""
        assert a2a_channel._handler is not None

    def test_app_initialized(self, a2a_channel):
        """Test ASGI app is initialized."""
        assert a2a_channel._app is not None


class TestExtractContent:
    """Tests for content extraction."""

    def test_extract_from_text_part(self, a2a_channel):
        """Test extracting text from a text part."""
        message = make_message("Hello, world!")
        content = a2a_channel._handler._extract_content(message)
        assert content == "Hello, world!"

    def test_extract_from_multiple_parts(self, a2a_channel):
        """Test extracting text from multiple parts."""
        message = Message(
            message_id=f"msg-{uuid.uuid4().hex[:8]}",
            role="user",
            parts=[
                Part(type="text", text="First"),
                Part(type="text", text="Second"),
            ],
        )
        content = a2a_channel._handler._extract_content(message)
        assert content == "First\nSecond"

    def test_extract_from_data_part(self, a2a_channel):
        """Test extracting JSON from a data part."""
        message = Message(
            message_id=f"msg-{uuid.uuid4().hex[:8]}",
            role="user",
            parts=[Part(type="data", data={"key": "value"})],
        )
        content = a2a_channel._handler._extract_content(message)
        assert '"key": "value"' in content

    def test_extract_from_empty_message(self, a2a_channel):
        """Test extracting from None message."""
        content = a2a_channel._handler._extract_content(None)
        assert content == ""


class TestMessageSend:
    """Tests for message/send handling."""

    @pytest.mark.asyncio
    async def test_message_send_routes_to_bus(self, a2a_channel, mock_bus):
        """Test on_message_send creates InboundMessage and publishes to bus."""
        message = make_message("Hello", context_id="test-ctx-1")
        params = MessageSendParams(message=message)
        
        task = await a2a_channel._handler.on_message_send(params)
        
        mock_bus.publish_inbound.assert_called_once()
        call_args = mock_bus.publish_inbound.call_args[0][0]
        assert isinstance(call_args, InboundMessage)
        assert call_args.channel == "a2a"
        assert call_args.chat_id == "test-ctx-1"
        assert call_args.content == "Hello"
        assert call_args.session_key_override == "test-ctx-1"
        assert task.context_id == "test-ctx-1"

    @pytest.mark.asyncio
    async def test_message_send_generates_context_id(self, a2a_channel, mock_bus):
        """Test on_message_send generates context_id if not provided."""
        message = make_message("Hello", context_id=None)
        params = MessageSendParams(message=message)
        
        task = await a2a_channel._handler.on_message_send(params)
        assert task.context_id.startswith("a2a:")


class TestDeliverResponse:
    """Tests for response delivery."""

    @pytest.mark.asyncio
    async def test_deliver_response_resolves_future(self, a2a_channel):
        """Test deliver_response resolves the pending task future."""
        future = asyncio.Future()
        a2a_channel._handler._pending_tasks["task-123"] = future

        result = a2a_channel._handler.deliver_response("task-123", "Response text")

        assert result is True
        assert future.done()
        assert future.result() == "Response text"

    @pytest.mark.asyncio
    async def test_deliver_response_unknown_task(self, a2a_channel):
        """Test deliver_response returns False for unknown task."""
        result = a2a_channel._handler.deliver_response("unknown-task", "Response")
        assert result is False


class TestSend:
    """Tests for send method."""

    @pytest.mark.asyncio
    async def test_send_resolves_pending_future(self, a2a_channel):
        """Test send() resolves the pending task future via metadata."""
        future = asyncio.Future()
        a2a_channel._handler._pending_tasks["task-123"] = future

        msg = OutboundMessage(
            channel="a2a",
            chat_id="ctx-456",
            content="Response text",
            metadata={"task_id": "task-123"},
        )

        await a2a_channel.send(msg)

        assert future.done()
        assert future.result() == "Response text"


class TestLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_dispatch_task(self, a2a_channel):
        """Test start() creates the dispatch task."""
        await a2a_channel.start()
        assert a2a_channel._dispatch_task is not None
        assert a2a_channel._running is True
        await a2a_channel.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_dispatch_task(self, a2a_channel):
        """Test stop() cancels the dispatch task."""
        await a2a_channel.start()
        await a2a_channel.stop()
        assert a2a_channel._running is False


class TestGetASGIApp:
    """Tests for get_asgi_app method."""

    def test_returns_starlette_app(self, a2a_channel):
        """Test get_asgi_app() returns a Starlette app."""
        app = a2a_channel.get_asgi_app()
        assert app is not None
        assert hasattr(app, 'routes')
