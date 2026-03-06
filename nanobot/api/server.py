"""OpenAI-compatible HTTP API server for nanobot.

Provides /v1/chat/completions and /v1/models endpoints.
Session isolation is enforced via the x-session-key request header.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from aiohttp import web
from loguru import logger

# Tools that must NOT run in multi-tenant API mode.
# Filesystem tools allow the LLM to read/write the shared workspace (including
# global MEMORY.md), and exec allows shell commands that can bypass filesystem
# restrictions (e.g. `cat ~/.nanobot/workspace/memory/MEMORY.md`).
_API_DISABLED_TOOLS: set[str] = {
    "read_file", "write_file", "edit_file", "list_dir", "exec",
}


# ---------------------------------------------------------------------------
# Per-session-key lock manager
# ---------------------------------------------------------------------------

class _SessionLocks:
    """Manages one asyncio.Lock per session key for serial execution."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._ref: dict[str, int] = {}  # reference count for cleanup

    def acquire(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
            self._ref[key] = 0
        self._ref[key] += 1
        return self._locks[key]

    def release(self, key: str) -> None:
        self._ref[key] -= 1
        if self._ref[key] <= 0:
            self._locks.pop(key, None)
            self._ref.pop(key, None)


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


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_chat_completions(request: web.Request) -> web.Response:
    """POST /v1/chat/completions"""

    # --- x-session-key validation ---
    session_key = request.headers.get("x-session-key", "").strip()
    if not session_key:
        return _error_json(400, "Missing required header: x-session-key")

    # --- Parse body ---
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        return _error_json(400, "messages field is required and must be a non-empty array")

    # Stream not yet supported
    if body.get("stream", False):
        return _error_json(400, "stream=true is not supported yet. Set stream=false or omit it.")

    # Extract last user message — nanobot manages its own multi-turn history
    user_content = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_content = msg.get("content", "")
            break
    if user_content is None:
        return _error_json(400, "messages must contain at least one user message")
    if isinstance(user_content, list):
        # Multi-modal content array — extract text parts
        user_content = " ".join(
            part.get("text", "") for part in user_content if part.get("type") == "text"
        )

    agent_loop = request.app["agent_loop"]
    timeout_s: float = request.app.get("request_timeout", 120.0)
    model_name: str = body.get("model") or request.app.get("model_name", "nanobot")
    locks: _SessionLocks = request.app["session_locks"]

    safe_key = session_key[:32] + ("…" if len(session_key) > 32 else "")
    logger.info("API request session_key={} content={}", safe_key, user_content[:80])

    _FALLBACK = "I've completed processing but have no response to give."

    lock = locks.acquire(session_key)
    try:
        async with lock:
            try:
                response_text = await asyncio.wait_for(
                    agent_loop.process_direct(
                        content=user_content,
                        session_key=session_key,
                        channel="api",
                        chat_id=session_key,
                        isolate_memory=True,
                        disabled_tools=_API_DISABLED_TOOLS,
                    ),
                    timeout=timeout_s,
                )

                if not response_text or not response_text.strip():
                    logger.warning("Empty response for session {}, retrying", safe_key)
                    response_text = await asyncio.wait_for(
                        agent_loop.process_direct(
                            content=user_content,
                            session_key=session_key,
                            channel="api",
                            chat_id=session_key,
                            isolate_memory=True,
                            disabled_tools=_API_DISABLED_TOOLS,
                        ),
                        timeout=timeout_s,
                    )
                    if not response_text or not response_text.strip():
                        logger.warning("Empty response after retry for session {}, using fallback", safe_key)
                        response_text = _FALLBACK

            except asyncio.TimeoutError:
                return _error_json(504, f"Request timed out after {timeout_s}s")
            except Exception:
                logger.exception("Error processing request for session {}", safe_key)
                return _error_json(500, "Internal server error", err_type="server_error")
    finally:
        locks.release(session_key)

    return web.json_response(_chat_completion_response(response_text, model_name))


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
    app["session_locks"] = _SessionLocks()

    app.router.add_post("/v1/chat/completions", handle_chat_completions)
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/health", handle_health)
    return app


def run_server(agent_loop, host: str = "0.0.0.0", port: int = 8900,
               model_name: str = "nanobot", request_timeout: float = 120.0) -> None:
    """Create and run the server (blocking)."""
    app = create_app(agent_loop, model_name=model_name, request_timeout=request_timeout)
    web.run_app(app, host=host, port=port, print=lambda msg: logger.info(msg))
