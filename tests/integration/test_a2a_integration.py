"""Integration tests for A2A channel with a2a-sdk."""

import pytest
import uuid
from unittest.mock import MagicMock

from a2a.types import Message, Part


@pytest.fixture
def mock_config():
    """Create a mock A2A config with skill dicts (as they would be in YAML config)."""
    config = MagicMock()
    config.agent_name = "Integration Test Agent"
    config.agent_url = "http://localhost:8000"
    config.agent_description = "Integration test agent"
    config.skills = [
        {"id": "test", "name": "Test", "description": "Test skill", "tags": []},
    ]
    return config


@pytest.fixture
async def a2a_app(mock_config):
    """Create A2A ASGI app for testing."""
    try:
        from nanobot.bus.queue import MessageBus
        from nanobot.channels.a2a import A2AChannel, A2A_AVAILABLE
    except ImportError:
        pytest.skip("a2a-sdk not installed")
        return

    if not A2A_AVAILABLE:
        pytest.skip("a2a-sdk not installed")
        return

    bus = MessageBus()
    channel = A2AChannel(mock_config, bus)
    await channel.start()

    yield channel.get_asgi_app(), channel

    await channel.stop()


class TestAgentCardEndpoint:
    """Tests for agent card discovery."""

    def test_agent_card_returns_json(self, a2a_app):
        """Test /.well-known/agent-card.json returns valid card."""
        from starlette.testclient import TestClient

        app, channel = a2a_app
        client = TestClient(app)

        response = client.get("/.well-known/agent-card.json")
        assert response.status_code == 200

        card = response.json()
        assert "name" in card
        assert "capabilities" in card
        assert card["name"] == "Integration Test Agent"

    def test_agent_card_has_capabilities(self, a2a_app):
        """Test agent card includes capabilities."""
        from starlette.testclient import TestClient

        app, channel = a2a_app
        client = TestClient(app)

        response = client.get("/.well-known/agent-card.json")
        card = response.json()

        assert "capabilities" in card
        # Streaming should be enabled
        assert card["capabilities"].get("streaming") is True


class TestMessageSend:
    """Tests for message/send JSON-RPC method."""

    def _make_message(self, text: str, contextId: str | None = None):
        """Helper to create a message."""
        return Message(
            message_id=f"msg-{uuid.uuid4().hex[:8]}",
            role="user",
            parts=[Part(type="text", text=text)],
            contextId=contextId,
        )

    def test_message_send_creates_task(self, a2a_app):
        """Test message/send creates a task."""
        from starlette.testclient import TestClient

        app, channel = a2a_app
        client = TestClient(app)

        message = self._make_message("Hello", contextId="test-ctx-1")
        response = client.post("/", json={
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": message.model_dump(mode='json', exclude_none=True),
            },
            "id": 1
        })

        assert response.status_code == 200
        result = response.json()
        assert "result" in result
        # Task should have an id
        assert "id" in result["result"]
        # Task status is a dict with 'state' field
        status = result["result"]["status"]
        assert isinstance(status, dict)
        assert status["state"] in ["working", "submitted"]

    def test_message_send_returns_contextId(self, a2a_app):
        """Test message/send returns the contextId."""
        from starlette.testclient import TestClient

        app, channel = a2a_app
        client = TestClient(app)

        message = self._make_message("Hello", contextId="my-context-123")
        response = client.post("/", json={
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": message.model_dump(mode='json', exclude_none=True),
            },
            "id": 2
        })

        assert response.status_code == 200
        result = response.json()
        assert result["result"]["contextId"] == "my-context-123"

    def test_message_send_with_no_context_still_creates_task(self, a2a_app):
        """Test message/send works even without contextId."""
        from starlette.testclient import TestClient

        app, channel = a2a_app
        client = TestClient(app)

        message = self._make_message("No context provided")
        response = client.post("/", json={
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": message.model_dump(mode='json', exclude_none=True),
            },
            "id": 3
        })

        assert response.status_code == 200
        result = response.json()
        # Should still create a task with a generated contextId
        assert "id" in result["result"]
        assert "contextId" in result["result"]


class TestJSONRPCFormat:
    """Tests for JSON-RPC protocol compliance."""

    def test_valid_jsonrpc_request(self, a2a_app):
        """Test that valid JSON-RPC requests are handled."""
        from starlette.testclient import TestClient

        app, channel = a2a_app
        client = TestClient(app)

        message = self._make_message("Test")
        response = client.post("/", json={
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": message.model_dump(mode='json', exclude_none=True),
            },
            "id": 100
        })

        result = response.json()
        # Should have matching id
        assert result["id"] == 100
        # Should have jsonrpc version
        assert result["jsonrpc"] == "2.0"

    def test_invalid_method_returns_error(self, a2a_app):
        """Test that invalid methods return JSON-RPC error."""
        from starlette.testclient import TestClient

        app, channel = a2a_app
        client = TestClient(app)

        response = client.post("/", json={
            "jsonrpc": "2.0",
            "method": "unknown/method",
            "params": {},
            "id": 1
        })

        result = response.json()
        assert "error" in result

    _make_message = TestMessageSend._make_message


class TestHealthCheck:
    """Basic health checks for the A2A server."""

    def test_server_responds_to_requests(self, a2a_app):
        """Test that the server responds to HTTP requests."""
        from starlette.testclient import TestClient

        app, channel = a2a_app
        client = TestClient(app)

        # Agent card should be available
        response = client.get("/.well-known/agent-card.json")
        assert response.status_code == 200
