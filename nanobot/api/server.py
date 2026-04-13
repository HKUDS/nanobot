"""OpenAI-compatible HTTP API server for a fixed nanobot session.

Provides /v1/chat/completions and /v1/models endpoints.
Supports both non-streaming and SSE streaming responses.
All requests route to a single persistent API session.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

API_SESSION_KEY = "api:default"
API_CHAT_ID = "default"


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _error_json(status: int, message: str, err_type: str = "invalid_request_error") -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": err_type, "code": status}},
        status=status,
    )


def _chat_completion_response(content: str, model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _chat_completion_chunk(
    delta: dict[str, str],
    model: str,
    completion_id: str,
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """Build an OpenAI-compatible streamed chunk."""
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def _response_text(value: Any) -> str:
    """Normalize process_direct output to plain assistant text."""
    if value is None:
        return ""
    if hasattr(value, "content"):
        return str(getattr(value, "content") or "")
    return str(value)


def _sse_frame(data: str) -> bytes:
    """Encode a single SSE frame."""
    return f"data: {data}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def _parse_request(body: dict[str, Any], app: web.Application):
    """Parse and validate chat completion request body.

    Returns (user_content, session_key, model_name, timeout_s, error_response).
    On validation failure *error_response* is set and other fields are None.
    """
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        return None, None, None, None, _error_json(400, "Only a single user message is supported")

    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        return None, None, None, None, _error_json(400, "Only a single user message is supported")

    user_content = message.get("content", "")
    if isinstance(user_content, list):
        user_content = " ".join(
            part.get("text", "") for part in user_content if part.get("type") == "text"
        )

    model_name: str = app.get("model_name", "nanobot")
    if (requested_model := body.get("model")) and requested_model != model_name:
        return None, None, None, None, _error_json(
            400, f"Only configured model '{model_name}' is available"
        )

    session_key = f"api:{body['session_id']}" if body.get("session_id") else API_SESSION_KEY
    timeout_s: float = app.get("request_timeout", 120.0)
    return user_content, session_key, model_name, timeout_s, None


# ---------------------------------------------------------------------------
# Non-streaming handler
# ---------------------------------------------------------------------------

async def _handle_non_streaming(
    agent_loop,
    user_content: str,
    session_key: str,
    model_name: str,
    timeout_s: float,
    session_lock: asyncio.Lock,
) -> web.Response:
    _FALLBACK = EMPTY_FINAL_RESPONSE_MESSAGE
    try:
        async with session_lock:
            try:
                response = await asyncio.wait_for(
                    agent_loop.process_direct(
                        content=user_content,
                        session_key=session_key,
                        channel="api",
                        chat_id=API_CHAT_ID,
                    ),
                    timeout=timeout_s,
                )
                response_text = _response_text(response)

                if not response_text or not response_text.strip():
                    logger.warning(
                        "Empty response for session {}, retrying",
                        session_key,
                    )
                    retry_response = await asyncio.wait_for(
                        agent_loop.process_direct(
                            content=user_content,
                            session_key=session_key,
                            channel="api",
                            chat_id=API_CHAT_ID,
                        ),
                        timeout=timeout_s,
                    )
                    response_text = _response_text(retry_response)
                    if not response_text or not response_text.strip():
                        logger.warning(
                            "Empty response after retry for session {}, using fallback",
                            session_key,
                        )
                        response_text = _FALLBACK

            except asyncio.TimeoutError:
                return _error_json(504, f"Request timed out after {timeout_s}s")
            except Exception:
                logger.exception("Error processing request for session {}", session_key)
                return _error_json(500, "Internal server error", err_type="server_error")
    except Exception:
        logger.exception("Unexpected API lock error for session {}", session_key)
        return _error_json(500, "Internal server error", err_type="server_error")

    return web.json_response(_chat_completion_response(response_text, model_name))


# ---------------------------------------------------------------------------
# SSE streaming handler
# ---------------------------------------------------------------------------

async def _handle_streaming(
    request: web.Request,
    agent_loop,
    user_content: str,
    session_key: str,
    model_name: str,
    timeout_s: float,
    session_lock: asyncio.Lock,
) -> web.StreamResponse:
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    # Send the initial chunk with the role
    initial_chunk = _chat_completion_chunk(
        delta={"role": "assistant"},
        model=model_name,
        completion_id=completion_id,
    )
    await resp.write(_sse_frame(json.dumps(initial_chunk, ensure_ascii=False)))

    async def on_stream(delta: str) -> None:
        chunk = _chat_completion_chunk(
            delta={"content": delta},
            model=model_name,
            completion_id=completion_id,
        )
        await resp.write(_sse_frame(json.dumps(chunk, ensure_ascii=False)))

    try:
        async with session_lock:
            await asyncio.wait_for(
                agent_loop.process_direct(
                    content=user_content,
                    session_key=session_key,
                    channel="api",
                    chat_id=API_CHAT_ID,
                    on_stream=on_stream,
                ),
                timeout=timeout_s,
            )
    except asyncio.TimeoutError:
        logger.warning("Streaming request timed out after {}s for session {}", timeout_s, session_key)
    except Exception:
        logger.exception("Error during streaming for session {}", session_key)

    # Send the final stop chunk and [DONE] sentinel
    stop_chunk = _chat_completion_chunk(
        delta={},
        model=model_name,
        completion_id=completion_id,
        finish_reason="stop",
    )
    await resp.write(_sse_frame(json.dumps(stop_chunk, ensure_ascii=False)))
    await resp.write(_sse_frame("[DONE]"))
    await resp.write_eof()
    return resp


# ---------------------------------------------------------------------------
# Main route handler
# ---------------------------------------------------------------------------

async def handle_chat_completions(request: web.Request) -> web.Response | web.StreamResponse:
    """POST /v1/chat/completions — supports both streaming and non-streaming."""

    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    user_content, session_key, model_name, timeout_s, err = _parse_request(body, request.app)
    if err is not None:
        return err

    agent_loop = request.app["agent_loop"]
    session_locks: dict[str, asyncio.Lock] = request.app["session_locks"]
    session_lock = session_locks.setdefault(session_key, asyncio.Lock())

    logger.info("API request session_key={} stream={} content={}",
                session_key, body.get("stream", False), user_content[:80])

    if body.get("stream", False):
        return await _handle_streaming(
            request, agent_loop, user_content, session_key,
            model_name, timeout_s, session_lock,
        )

    return await _handle_non_streaming(
        agent_loop, user_content, session_key,
        model_name, timeout_s, session_lock,
    )


async def handle_models(request: web.Request) -> web.Response:
    """GET /v1/models"""
    model_name = request.app.get("model_name", "nanobot")
    return web.json_response({
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": 0,
                "owned_by": "nanobot",
            }
        ],
    })


async def handle_health(request: web.Request) -> web.Response:
    """GET /health"""
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(agent_loop, model_name: str = "nanobot", request_timeout: float = 120.0) -> web.Application:
    """Create the aiohttp application.

    Args:
        agent_loop: An initialized AgentLoop instance.
        model_name: Model name reported in responses.
        request_timeout: Per-request timeout in seconds.
    """
    app = web.Application()
    app["agent_loop"] = agent_loop
    app["model_name"] = model_name
    app["request_timeout"] = request_timeout
    app["session_locks"] = {}  # per-user locks, keyed by session_key

    app.router.add_post("/v1/chat/completions", handle_chat_completions)
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/health", handle_health)
    return app
