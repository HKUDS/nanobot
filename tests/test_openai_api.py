"""Focused tests for the fixed-session OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from nanobot.api.server import (
    API_CHAT_ID,
    API_SESSION_KEY,
    _chat_completion_chunk,
    _chat_completion_response,
    _error_json,
    _sse_frame,
    create_app,
    handle_chat_completions,
)

try:
    from aiohttp.test_utils import TestClient, TestServer

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

pytest_plugins = ("pytest_asyncio",)


def _make_mock_agent(response_text: str = "mock response") -> MagicMock:
    agent = MagicMock()
    agent.process_direct = AsyncMock(return_value=response_text)
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()
    return agent


@pytest.fixture
def mock_agent():
    return _make_mock_agent()


@pytest.fixture
def app(mock_agent):
    return create_app(mock_agent, model_name="test-model", request_timeout=10.0)


@pytest_asyncio.fixture
async def aiohttp_client():
    clients: list[TestClient] = []

    async def _make_client(app):
        client = TestClient(TestServer(app))
        await client.start_server()
        clients.append(client)
        return client

    try:
        yield _make_client
    finally:
        for client in clients:
            await client.close()


def test_error_json() -> None:
    resp = _error_json(400, "bad request")
    assert resp.status == 400
    body = json.loads(resp.body)
    assert body["error"]["message"] == "bad request"
    assert body["error"]["code"] == 400


def test_chat_completion_response() -> None:
    result = _chat_completion_response("hello world", "test-model")
    assert result["object"] == "chat.completion"
    assert result["model"] == "test-model"
    assert result["choices"][0]["message"]["content"] == "hello world"
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["id"].startswith("chatcmpl-")


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_missing_messages_returns_400(aiohttp_client, app) -> None:
    client = await aiohttp_client(app)
    resp = await client.post("/v1/chat/completions", json={"model": "test"})
    assert resp.status == 400


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_no_user_message_returns_400(aiohttp_client, app) -> None:
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "system", "content": "you are a bot"}]},
    )
    assert resp.status == 400


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_stream_true_returns_sse(aiohttp_client) -> None:
    """stream=true should return a text/event-stream response with SSE chunks."""
    deltas: list[str] = ["Hello", " world", "!"]

    async def streaming_process(content, session_key="", channel="", chat_id="", on_stream=None):
        if on_stream:
            for d in deltas:
                await on_stream(d)
        return "Hello world!"

    agent = MagicMock()
    agent.process_direct = streaming_process
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="test-model")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status == 200
    assert "text/event-stream" in resp.headers.get("Content-Type", "")

    raw = await resp.read()
    text = raw.decode("utf-8")
    lines = [l for l in text.strip().split("\n") if l.startswith("data: ")]

    # Parse SSE frames
    chunks = []
    for line in lines:
        payload = line[len("data: "):]
        if payload == "[DONE]":
            chunks.append("[DONE]")
        else:
            chunks.append(json.loads(payload))

    # First chunk: role
    assert chunks[0]["object"] == "chat.completion.chunk"
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant"}

    # Content chunks
    content_deltas = [
        c["choices"][0]["delta"]["content"]
        for c in chunks[1:]
        if isinstance(c, dict) and "content" in c.get("choices", [{}])[0].get("delta", {})
    ]
    assert content_deltas == deltas

    # Stop chunk (second to last)
    stop_chunk = chunks[-2]
    assert stop_chunk["choices"][0]["finish_reason"] == "stop"

    # [DONE] sentinel (last)
    assert chunks[-1] == "[DONE]"


@pytest.mark.asyncio
async def test_model_mismatch_returns_400() -> None:
    request = MagicMock()
    request.json = AsyncMock(
        return_value={
            "model": "other-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
    )
    request.app = {
        "agent_loop": _make_mock_agent(),
        "model_name": "test-model",
        "request_timeout": 10.0,
        "session_locks": {},
    }

    resp = await handle_chat_completions(request)
    assert resp.status == 400
    body = json.loads(resp.body)
    assert "test-model" in body["error"]["message"]


@pytest.mark.asyncio
async def test_single_user_message_required() -> None:
    request = MagicMock()
    request.json = AsyncMock(
        return_value={
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "previous reply"},
            ],
        }
    )
    request.app = {
        "agent_loop": _make_mock_agent(),
        "model_name": "test-model",
        "request_timeout": 10.0,
        "session_locks": {},
    }

    resp = await handle_chat_completions(request)
    assert resp.status == 400
    body = json.loads(resp.body)
    assert "single user message" in body["error"]["message"].lower()


@pytest.mark.asyncio
async def test_single_user_message_must_have_user_role() -> None:
    request = MagicMock()
    request.json = AsyncMock(
        return_value={
            "messages": [{"role": "system", "content": "you are a bot"}],
        }
    )
    request.app = {
        "agent_loop": _make_mock_agent(),
        "model_name": "test-model",
        "request_timeout": 10.0,
        "session_locks": {},
    }

    resp = await handle_chat_completions(request)
    assert resp.status == 400
    body = json.loads(resp.body)
    assert "single user message" in body["error"]["message"].lower()


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_successful_request_uses_fixed_api_session(aiohttp_client, mock_agent) -> None:
    app = create_app(mock_agent, model_name="test-model")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "mock response"
    assert body["model"] == "test-model"
    mock_agent.process_direct.assert_called_once_with(
        content="hello",
        session_key=API_SESSION_KEY,
        channel="api",
        chat_id=API_CHAT_ID,
    )


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_followup_requests_share_same_session_key(aiohttp_client) -> None:
    call_log: list[str] = []

    async def fake_process(content, session_key="", channel="", chat_id=""):
        call_log.append(session_key)
        return f"reply to {content}"

    agent = MagicMock()
    agent.process_direct = fake_process
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    r1 = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "first"}]},
    )
    r2 = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "second"}]},
    )

    assert r1.status == 200
    assert r2.status == 200
    assert call_log == [API_SESSION_KEY, API_SESSION_KEY]


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_fixed_session_requests_are_serialized(aiohttp_client) -> None:
    order: list[str] = []

    async def slow_process(content, session_key="", channel="", chat_id=""):
        order.append(f"start:{content}")
        await asyncio.sleep(0.1)
        order.append(f"end:{content}")
        return content

    agent = MagicMock()
    agent.process_direct = slow_process
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)

    async def send(msg: str):
        return await client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": msg}]},
        )

    r1, r2 = await asyncio.gather(send("first"), send("second"))
    assert r1.status == 200
    assert r2.status == 200
    # Verify serialization: one process must fully finish before the other starts
    if order[0] == "start:first":
        assert order.index("end:first") < order.index("start:second")
    else:
        assert order.index("end:second") < order.index("start:first")


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_models_endpoint(aiohttp_client, app) -> None:
    client = await aiohttp_client(app)
    resp = await client.get("/v1/models")
    assert resp.status == 200
    body = await resp.json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "test-model"


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_health_endpoint(aiohttp_client, app) -> None:
    client = await aiohttp_client(app)
    resp = await client.get("/health")
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_multimodal_content_extracts_text(aiohttp_client, mock_agent) -> None:
    app = create_app(mock_agent, model_name="m")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "describe this"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                    ],
                }
            ]
        },
    )
    assert resp.status == 200
    mock_agent.process_direct.assert_called_once_with(
        content="describe this",
        session_key=API_SESSION_KEY,
        channel="api",
        chat_id=API_CHAT_ID,
    )


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_empty_response_retry_then_success(aiohttp_client) -> None:
    call_count = 0

    async def sometimes_empty(content, session_key="", channel="", chat_id=""):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return ""
        return "recovered response"

    agent = MagicMock()
    agent.process_direct = sometimes_empty
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == "recovered response"
    assert call_count == 2


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_empty_response_falls_back(aiohttp_client) -> None:
    from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

    call_count = 0

    async def always_empty(content, session_key="", channel="", chat_id=""):
        nonlocal call_count
        call_count += 1
        return ""

    agent = MagicMock()
    agent.process_direct = always_empty
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["choices"][0]["message"]["content"] == EMPTY_FINAL_RESPONSE_MESSAGE
    assert call_count == 2


# ---------------------------------------------------------------------------
# Streaming helper unit tests
# ---------------------------------------------------------------------------

def test_chat_completion_chunk_format() -> None:
    chunk = _chat_completion_chunk(
        delta={"content": "hi"},
        model="test-model",
        completion_id="chatcmpl-abc123",
        finish_reason=None,
    )
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["id"] == "chatcmpl-abc123"
    assert chunk["model"] == "test-model"
    assert chunk["choices"][0]["delta"] == {"content": "hi"}
    assert chunk["choices"][0]["finish_reason"] is None


def test_chat_completion_chunk_with_stop() -> None:
    chunk = _chat_completion_chunk(
        delta={},
        model="m",
        completion_id="chatcmpl-xyz",
        finish_reason="stop",
    )
    assert chunk["choices"][0]["finish_reason"] == "stop"
    assert chunk["choices"][0]["delta"] == {}


def test_sse_frame_encoding() -> None:
    frame = _sse_frame('{"key": "value"}')
    assert frame == b'data: {"key": "value"}\n\n'


def test_sse_frame_done_sentinel() -> None:
    frame = _sse_frame("[DONE]")
    assert frame == b"data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Streaming integration tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_stream_false_still_returns_json(aiohttp_client, mock_agent) -> None:
    """Explicitly setting stream=false should return a normal JSON response."""
    app = create_app(mock_agent, model_name="test-model")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "stream": False},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "mock response"


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_stream_with_custom_session_id(aiohttp_client) -> None:
    """stream=true with session_id should use the custom session key."""
    captured_keys: list[str] = []

    async def track_session(content, session_key="", channel="", chat_id="", on_stream=None):
        captured_keys.append(session_key)
        if on_stream:
            await on_stream("ok")
        return "ok"

    agent = MagicMock()
    agent.process_direct = track_session
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
            "session_id": "my-session",
        },
    )
    assert resp.status == 200
    assert captured_keys == ["api:my-session"]


@pytest.mark.skipif(not HAS_AIOHTTP, reason="aiohttp not installed")
@pytest.mark.asyncio
async def test_stream_empty_content_still_sends_done(aiohttp_client) -> None:
    """Even if on_stream is never called, the SSE response should end with [DONE]."""
    async def no_stream(content, session_key="", channel="", chat_id="", on_stream=None):
        # on_stream is provided but never called
        return ""

    agent = MagicMock()
    agent.process_direct = no_stream
    agent._connect_mcp = AsyncMock()
    agent.close_mcp = AsyncMock()

    app = create_app(agent, model_name="m")
    client = await aiohttp_client(app)
    resp = await client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}], "stream": True},
    )
    assert resp.status == 200
    raw = await resp.read()
    text = raw.decode("utf-8")
    assert "data: [DONE]" in text
