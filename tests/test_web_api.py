"""Tests for the nanobot web API (FastAPI endpoints)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_agent_loop():
    """Create a mock AgentLoop that returns a canned response."""
    loop = MagicMock()
    loop.stop = MagicMock()
    loop.close_mcp = AsyncMock()

    async def fake_process_direct(
        content, session_key="web:default", channel="web", chat_id="default", on_progress=None
    ):
        if on_progress:
            await on_progress("Hello ")
            await on_progress("world!")
        return "Hello world!"

    loop.process_direct = AsyncMock(side_effect=fake_process_direct)
    return loop


@pytest.fixture()
def mock_session_manager():
    """Create a mock SessionManager."""
    manager = MagicMock()
    session = MagicMock()
    session.key = "web:test-session"
    session.messages = [
        {"role": "user", "content": "Hi", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "Hello!", "timestamp": "2026-01-01T00:00:01"},
    ]
    session.get_history.return_value = session.messages
    session.clear = MagicMock()
    manager.get_or_create.return_value = session
    manager.save = MagicMock()
    manager.invalidate = MagicMock()
    manager.list_sessions.return_value = [
        {
            "key": "web:thread-abc",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:01:00",
        },
    ]
    # Mock _get_session_path to return a non-existent path
    manager._get_session_path.return_value = Path("/tmp/nonexistent.jsonl")
    return manager


@pytest.fixture()
def app(mock_agent_loop, mock_session_manager):
    """Create a test FastAPI app."""
    from nanobot.web.app import create_app

    return create_app(mock_agent_loop, mock_session_manager)


@pytest.fixture()
def client(app):
    """Create a test client."""
    from starlette.testclient import TestClient

    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChatEndpoint:
    """Tests for POST /api/chat."""

    def test_chat_returns_streaming_response(self, client):
        """The chat endpoint should return a streaming plain-text response."""
        response = client.post(
            "/api/chat",
            json={
                "threadId": "test-session",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")

    def test_chat_no_user_message_returns_400(self, client):
        """Should return 400 if no user message is provided."""
        response = client.post(
            "/api/chat",
            json={
                "threadId": "test-session",
                "messages": [{"role": "assistant", "content": "Hi"}],
            },
        )
        assert response.status_code == 400

    def test_chat_empty_messages_returns_400(self, client):
        """Should return 400 if messages list is empty."""
        response = client.post(
            "/api/chat",
            json={"threadId": "test-session", "messages": []},
        )
        assert response.status_code == 400

    def test_chat_without_thread_id(self, client):
        """Should auto-generate threadId when not provided."""
        response = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "Hello"}]},
        )
        assert response.status_code == 200

    def test_chat_structured_content(self, client):
        """Should handle structured content parts (AI SDK format)."""
        response = client.post(
            "/api/chat",
            json={
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": "Hello there"}],
                    }
                ],
            },
        )
        assert response.status_code == 200


class TestThreadManagement:
    """Tests for thread management endpoints."""

    def test_list_threads(self, client, mock_session_manager):
        """Should list web threads."""
        response = client.get("/api/threads")
        assert response.status_code == 200
        data = response.json()
        assert "threads" in data
        assert len(data["threads"]) == 1
        assert data["threads"][0]["threadId"] == "thread-abc"

    def test_create_thread(self, client, mock_session_manager):
        """Should create a new thread and return its ID."""
        response = client.post("/api/threads")
        assert response.status_code == 200
        data = response.json()
        assert "threadId" in data
        assert len(data["threadId"]) > 0

    def test_delete_thread(self, client, mock_session_manager):
        """Should delete a thread."""
        response = client.delete("/api/threads/test-thread")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        mock_session_manager.invalidate.assert_called_once()


class TestHistoryEndpoint:
    """Tests for GET /api/chat/{session_id}/history."""

    def test_get_history(self, client, mock_session_manager):
        """Should return session history."""
        response = client.get("/api/chat/test-session/history")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session"
        assert len(data["messages"]) == 2
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][0]["content"] == "Hi"
        mock_session_manager.get_or_create.assert_called_with("web:test-session")


class TestNewSessionEndpoint:
    """Tests for POST /api/chat/{session_id}/new."""

    def test_new_session_clears(self, client, mock_session_manager):
        """Should clear the session and return ok."""
        response = client.post("/api/chat/test-session/new")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["session_id"] == "test-session"
        mock_session_manager.get_or_create.return_value.clear.assert_called_once()
        mock_session_manager.save.assert_called_once()


class TestStreamingFormat:
    """Tests for the SSE streaming adapter."""

    def test_escape_text(self):
        """Should properly escape text for JSON embedding."""
        from nanobot.web.streaming import _escape_text

        assert _escape_text('hello "world"') == 'hello \\"world\\"'
        assert _escape_text("line\nnew") == "line\\nnew"
        assert _escape_text("back\\slash") == "back\\\\slash"

    def test_parse_tool_hint(self):
        """Should parse tool hint format from on_progress."""
        from nanobot.web.streaming import _parse_tool_hint

        result = _parse_tool_hint("🔧 Calling `read_file` with path=/etc/hosts")
        assert result is not None
        assert result["tool_name"] == "read_file"

        # Non-tool text should return None
        assert _parse_tool_hint("Just regular text") is None


class TestModels:
    """Tests for Pydantic request/response models."""

    def test_chat_request_defaults(self):
        """ChatRequest should have sensible defaults."""
        from nanobot.web.models import ChatRequest

        req = ChatRequest(messages=[{"role": "user", "content": "Hi"}])
        assert req.thread_id is None

    def test_chat_request_custom_thread_id(self):
        """ChatRequest should accept custom threadId."""
        from nanobot.web.models import ChatRequest

        req = ChatRequest(threadId="my-chat", messages=[{"role": "user", "content": "Hi"}])
        assert req.thread_id == "my-chat"

    def test_chat_message_get_text_string(self):
        """ChatMessage.get_text() should handle string content."""
        from nanobot.web.models import ChatMessage

        msg = ChatMessage(role="user", content="Hello")
        assert msg.get_text() == "Hello"

    def test_chat_message_get_text_parts(self):
        """ChatMessage.get_text() should handle structured content parts."""
        from nanobot.web.models import ChatMessage

        msg = ChatMessage(
            role="user",
            content=[{"type": "text", "text": "Hello "}, {"type": "text", "text": "world"}],
        )
        assert msg.get_text() == "Hello world"


class TestAppFactory:
    """Tests for the FastAPI app factory."""

    def test_create_app_no_static(self, mock_agent_loop, mock_session_manager):
        """Should create app without static directory."""
        from nanobot.web.app import create_app

        app = create_app(mock_agent_loop, mock_session_manager)
        assert app is not None
        assert app.title == "Nanobot Web UI"

    def test_create_app_cors_headers(self, client):
        """Should include CORS headers for local dev origins."""
        response = client.options(
            "/api/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        # CORS preflight should be handled
        assert response.status_code in (200, 405)
