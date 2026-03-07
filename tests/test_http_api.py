"""Tests for HTTP API channel."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import HTTPAPIConfig


# --- HTTPAPIConfig tests ---

def test_http_api_config_defaults():
    cfg = HTTPAPIConfig()
    assert cfg.enabled is False
    assert cfg.auth_token == ""


def test_http_api_config_in_gateway():
    from nanobot.config.schema import GatewayConfig
    gw = GatewayConfig()
    assert gw.api.enabled is False
    assert gw.api.auth_token == ""


def test_http_api_config_enabled():
    cfg = HTTPAPIConfig(enabled=True, auth_token="test-token-123")
    assert cfg.enabled is True
    assert cfg.auth_token == "test-token-123"


# --- FastAPI app endpoint tests (using TestClient) ---

def _make_test_client(auth_token: str = ""):
    """Create a FastAPI TestClient with mocked agent."""
    from nanobot.channels.http_api import HTTPAPIChannel

    config = HTTPAPIConfig(enabled=True, auth_token=auth_token)
    mock_agent = MagicMock()
    mock_agent.process_direct = AsyncMock(return_value="Hello from nanobot!")

    channel = HTTPAPIChannel(config, mock_agent)
    app = channel._create_app()

    from starlette.testclient import TestClient
    return TestClient(app), mock_agent


def test_health_endpoint():
    """GET /api/v1/health returns ok."""
    client, _ = _make_test_client()
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_chat_endpoint():
    """POST /api/v1/chat returns agent response."""
    client, mock_agent = _make_test_client()
    resp = client.post("/api/v1/chat", json={
        "message": "Hello",
        "session_key": "test-session",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["response"] == "Hello from nanobot!"
    assert data["session_key"] == "test-session"
    mock_agent.process_direct.assert_called_once_with(
        content="Hello",
        session_key="test-session",
        channel="api",
        chat_id="default",
    )


def test_chat_endpoint_default_session():
    """POST /api/v1/chat uses default session_key."""
    client, mock_agent = _make_test_client()
    resp = client.post("/api/v1/chat", json={"message": "Hi"})
    assert resp.status_code == 200
    assert resp.json()["session_key"] == "api:default"


def test_chat_endpoint_missing_message():
    """POST /api/v1/chat without message returns 422."""
    client, _ = _make_test_client()
    resp = client.post("/api/v1/chat", json={})
    assert resp.status_code == 422


def test_chat_endpoint_with_auth():
    """POST /api/v1/chat with correct bearer token succeeds."""
    client, _ = _make_test_client(auth_token="my-token")
    resp = client.post(
        "/api/v1/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer my-token"},
    )
    assert resp.status_code == 200


def test_chat_endpoint_auth_rejected():
    """POST /api/v1/chat without token returns 401 when auth configured."""
    client, _ = _make_test_client(auth_token="my-token")
    resp = client.post("/api/v1/chat", json={"message": "Hello"})
    assert resp.status_code == 401


def test_chat_endpoint_wrong_token():
    """POST /api/v1/chat with wrong token returns 403."""
    client, _ = _make_test_client(auth_token="my-token")
    resp = client.post(
        "/api/v1/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 403


def test_chat_endpoint_invalid_auth_format():
    """POST /api/v1/chat with non-Bearer format returns 401."""
    client, _ = _make_test_client(auth_token="my-token")
    resp = client.post(
        "/api/v1/chat",
        json={"message": "Hello"},
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401


def test_health_no_auth_required():
    """GET /api/v1/health does not require auth even when configured."""
    client, _ = _make_test_client(auth_token="my-token")
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_chat_session_isolation():
    """Two requests with different session_keys use separate sessions."""
    client, mock_agent = _make_test_client()

    client.post("/api/v1/chat", json={"message": "A", "session_key": "user-1"})
    client.post("/api/v1/chat", json={"message": "B", "session_key": "user-2"})

    calls = mock_agent.process_direct.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["session_key"] == "user-1"
    assert calls[1].kwargs["session_key"] == "user-2"
