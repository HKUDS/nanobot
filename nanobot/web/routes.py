"""FastAPI route definitions for the web chat API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from nanobot.web.models import (
    ChatRequest,
    HistoryMessage,
    HistoryResponse,
    ThreadInfo,
    ThreadListResponse,
)
from nanobot.web.streaming import stream_agent_response

router = APIRouter(prefix="/api")

WEB_PREFIX = "web:"


def _session_key(thread_id: str) -> str:
    """Convert a threadId to a session key."""
    return f"{WEB_PREFIX}{thread_id}"


def _thread_id(session_key: str) -> str:
    """Extract threadId from a session key."""
    return session_key.removeprefix(WEB_PREFIX)


def _thread_title(session: object) -> str:
    """Derive a short title from the first user message in a session."""
    messages: list[dict] = getattr(session, "messages", [])
    for m in messages:
        if m.get("role") == "user":
            text: str = m.get("content", "")
            if len(text) > 50:
                return text[:50] + "..."
            return text or "New Chat"
    return "New Chat"


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """Stream a chat response using the Vercel AI SDK Data Stream Protocol."""
    agent_loop = request.app.state.agent_loop
    session_manager = request.app.state.session_manager

    # Use the last user message as the content to process
    user_messages = [m for m in body.messages if m.role == "user"]
    if not user_messages:
        return JSONResponse(status_code=400, content={"error": "No user message provided"})

    content = user_messages[-1].get_text()

    # Use threadId from request or generate a new one
    thread_id = body.thread_id or str(uuid.uuid4())
    session_key = _session_key(thread_id)

    # Ensure session exists
    session_manager.get_or_create(session_key)

    async def event_generator():
        async for event in stream_agent_response(agent_loop, content, session_key):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Thread management (for assistant-ui ThreadList)
# ---------------------------------------------------------------------------


@router.get("/threads")
async def list_threads(request: Request):
    """List all web chat threads."""
    session_manager = request.app.state.session_manager
    all_sessions = session_manager.list_sessions()

    threads: list[ThreadInfo] = []
    for info in all_sessions:
        key: str = info.get("key", "")
        if not key.startswith(WEB_PREFIX):
            continue
        tid = _thread_id(key)
        # Load session to get title
        session = session_manager.get_or_create(key)
        threads.append(
            ThreadInfo(
                threadId=tid,
                title=_thread_title(session),
                createdAt=info.get("created_at"),
                updatedAt=info.get("updated_at"),
            )
        )

    return ThreadListResponse(threads=threads)


@router.post("/threads")
async def create_thread(request: Request):
    """Create a new thread and return its ID."""
    session_manager = request.app.state.session_manager
    thread_id = str(uuid.uuid4())
    session_key = _session_key(thread_id)
    session_manager.get_or_create(session_key)
    session_manager.save(session_manager.get_or_create(session_key))
    return {"threadId": thread_id}


@router.delete("/threads/{thread_id}")
async def delete_thread(request: Request, thread_id: str):
    """Delete a thread and its session data."""
    session_manager = request.app.state.session_manager
    session_key = _session_key(thread_id)
    session = session_manager.get_or_create(session_key)
    session.clear()
    session_manager.save(session)
    session_manager.invalidate(session_key)
    # Remove the file from disk
    path = session_manager._get_session_path(session_key)
    if path.exists():
        path.unlink()
    return {"status": "ok", "threadId": thread_id}


# ---------------------------------------------------------------------------
# Legacy endpoints (kept for backward compatibility)
# ---------------------------------------------------------------------------


@router.get("/chat/{session_id}/history")
async def get_history(request: Request, session_id: str):
    """Return the message history for a session."""
    session_manager = request.app.state.session_manager
    session_key = _session_key(session_id)
    session = session_manager.get_or_create(session_key)
    history = session.get_history()

    messages = [
        HistoryMessage(
            role=m.get("role", ""),
            content=m.get("content", ""),
            timestamp=m.get("timestamp"),
            tool_calls=m.get("tool_calls"),
        )
        for m in history
    ]

    return HistoryResponse(session_id=session_id, messages=messages)


@router.post("/chat/{session_id}/new")
async def new_session(request: Request, session_id: str):
    """Clear a session to start a new conversation."""
    session_manager = request.app.state.session_manager
    session_key = _session_key(session_id)
    session = session_manager.get_or_create(session_key)
    session.clear()
    session_manager.save(session)
    return {"status": "ok", "session_id": session_id}
