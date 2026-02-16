"""Tests for HTTP API channel."""

from unittest.mock import AsyncMock, patch, MagicMock

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


# --- HTTPAPIChannel._check_auth tests ---

def _make_channel(auth_token: str = ""):
    """Create an HTTPAPIChannel with a mocked agent."""
    from nanobot.channels.http_api import HTTPAPIChannel
    config = HTTPAPIConfig(enabled=True, auth_token=auth_token)
    mock_agent = MagicMock()
    return HTTPAPIChannel(config, mock_agent)


def _make_request(auth_header: str | None = None):
    """Create a mock request with optional auth header."""
    request = MagicMock()
    headers = {}
    if auth_header is not None:
        headers["authorization"] = auth_header
    request.headers = headers
    return request


def test_check_auth_no_token_configured():
    """No auth required when auth_token is empty."""
    channel = _make_channel(auth_token="")
    request = _make_request()
    # Should not raise
    channel._check_auth(request)


def test_check_auth_valid_token():
    """Valid bearer token passes."""
    channel = _make_channel(auth_token="secret123")
    request = _make_request(auth_header="Bearer secret123")
    channel._check_auth(request)


def test_check_auth_missing_header():
    """Missing auth header returns 401."""
    from fastapi import HTTPException
    channel = _make_channel(auth_token="secret123")
    request = _make_request()
    with pytest.raises(HTTPException) as exc_info:
        channel._check_auth(request)
    assert exc_info.value.status_code == 401


def test_check_auth_wrong_token():
    """Wrong token returns 403."""
    from fastapi import HTTPException
    channel = _make_channel(auth_token="secret123")
    request = _make_request(auth_header="Bearer wrongtoken")
    with pytest.raises(HTTPException) as exc_info:
        channel._check_auth(request)
    assert exc_info.value.status_code == 403


def test_check_auth_invalid_format():
    """Non-Bearer format returns 401."""
    from fastapi import HTTPException
    channel = _make_channel(auth_token="secret123")
    request = _make_request(auth_header="Basic dXNlcjpwYXNz")
    with pytest.raises(HTTPException) as exc_info:
        channel._check_auth(request)
    assert exc_info.value.status_code == 401


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


def test_health_no_auth_required():
    """GET /api/v1/health does not require auth even when configured."""
    client, _ = _make_test_client(auth_token="my-token")
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
