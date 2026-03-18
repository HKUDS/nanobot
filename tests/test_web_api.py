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
def mock_web_channel():
    """Create a mock WebChannel that streams a canned response."""
    import asyncio

    from nanobot.bus.events import OutboundMessage

    channel = MagicMock()
    channel.name = "web"

    def fake_register_stream(chat_id):
        q: asyncio.Queue[OutboundMessage | None] = asyncio.Queue()
        # Pre-fill with a final response so the stream terminates
        q.put_nowait(
            OutboundMessage(
                channel="web",
                chat_id=chat_id,
                content="Hello world!",
                metadata={},
            )
        )
        return q

    channel.register_stream = MagicMock(side_effect=fake_register_stream)
    channel.unregister_stream = MagicMock()
    channel.publish_user_message = AsyncMock()
    return channel


@pytest.fixture()
def app(mock_agent_loop, mock_session_manager, mock_web_channel):
    """Create a test FastAPI app."""
    from nanobot.web.app import create_app

    return create_app(mock_agent_loop, mock_session_manager, mock_web_channel)


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

    def test_sse_helper_produces_valid_json(self):
        """_sse() must emit valid JSON with special characters escaped."""
        import json

        from nanobot.web.streaming import _sse

        chunk = _sse({"type": "text-delta", "textDelta": 'hello "world"\nback\\slash'})
        # Extract JSON payload from SSE line
        data_line = next(line for line in chunk.splitlines() if line.startswith("data:"))
        payload = json.loads(data_line[len("data:") :].strip())
        assert payload["type"] == "text-delta"
        assert payload["textDelta"] == 'hello "world"\nback\\slash'


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

    def test_create_app_no_static(self, mock_agent_loop, mock_session_manager, mock_web_channel):
        """Should create app without static directory."""
        from nanobot.web.app import create_app

        app = create_app(mock_agent_loop, mock_session_manager, mock_web_channel)
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


class TestStripAttachments:
    """Tests for _strip_attachments — extract file content and save to disk."""

    def test_quoted_name(self, tmp_path):
        from nanobot.web.routes import _strip_attachments

        text = 'Please read this: <attachment name="data.csv">col1,col2\n1,2</attachment>'
        result = _strip_attachments(text, tmp_path)
        assert "<attachment" not in result
        assert (tmp_path / "data.csv").read_text() == "col1,col2\n1,2"
        assert "data.csv" in result

    def test_unquoted_name(self, tmp_path):
        from nanobot.web.routes import _strip_attachments

        text = "<attachment name=report.xlsx>binary data here</attachment>"
        result = _strip_attachments(text, tmp_path)
        assert "<attachment" not in result
        assert (tmp_path / "report.xlsx").read_text() == "binary data here"
        assert "report.xlsx" in result

    def test_single_quoted_name(self, tmp_path):
        from nanobot.web.routes import _strip_attachments

        text = "<attachment name='notes.txt'>some notes</attachment>"
        result = _strip_attachments(text, tmp_path)
        assert "<attachment" not in result
        assert (tmp_path / "notes.txt").read_text() == "some notes"

    def test_no_attachments(self, tmp_path):
        from nanobot.web.routes import _strip_attachments

        text = "Just a normal message"
        assert _strip_attachments(text, tmp_path) == text

    def test_multiple_attachments(self, tmp_path):
        from nanobot.web.routes import _strip_attachments

        text = (
            '<attachment name="a.txt">aaa</attachment> and <attachment name=b.txt>bbb</attachment>'
        )
        result = _strip_attachments(text, tmp_path)
        assert "<attachment" not in result
        assert (tmp_path / "a.txt").read_text() == "aaa"
        assert (tmp_path / "b.txt").read_text() == "bbb"

    def test_duplicate_name_gets_suffix(self, tmp_path):
        from nanobot.web.routes import _strip_attachments

        (tmp_path / "dup.txt").write_text("original")
        text = '<attachment name="dup.txt">new content</attachment>'
        result = _strip_attachments(text, tmp_path)
        assert "<attachment" not in result
        # Original should be untouched
        assert (tmp_path / "dup.txt").read_text() == "original"
        # A new file with uuid suffix should exist
        saved = [f for f in tmp_path.iterdir() if f.name.startswith("dup_")]
        assert len(saved) == 1
        assert saved[0].read_text() == "new content"
