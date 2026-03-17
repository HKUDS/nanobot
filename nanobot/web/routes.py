"""FastAPI route definitions for the web chat API."""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse

from nanobot.web.models import (
    ChatMessage,
    ChatRequest,
    HistoryMessage,
    HistoryResponse,
    ThreadInfo,
    ThreadListResponse,
)
from nanobot.web.streaming import stream_agent_response

router = APIRouter(prefix="/api")

WEB_PREFIX = "web:"

# Matches <attachment name="…">…</attachment> blocks injected by assistant-ui
# Handles both quoted (name="file.csv") and unquoted (name=file.csv) attributes
_ATTACHMENT_RE = re.compile(
    r"<attachment\b[^>]*?name=[\"']?([^\"'>\s]+)[\"']?[^>]*>(.*?)</attachment>",
    re.DOTALL,
)


def _session_key(thread_id: str) -> str:
    return f"{WEB_PREFIX}{thread_id}"


def _thread_id(session_key: str) -> str:
    return session_key.removeprefix(WEB_PREFIX)


def _thread_title(session: object) -> str:
    messages: list[dict] = getattr(session, "messages", [])
    for m in messages:
        if m.get("role") == "user":
            text: str = m.get("content", "")
            if len(text) > 50:
                return text[:50] + "..."
            return text or "New Chat"
    return "New Chat"


def _strip_attachments(text: str, uploads_dir: Path) -> str:
    """Strip <attachment> blocks, save file content to disk, return cleaned text.

    Any ``<attachment name="file.csv">…data…</attachment>`` blocks are
    extracted, saved under *uploads_dir*, and replaced with a short
    ``[Attached file: uploads/file.csv]`` note so the agent can use its
    file-reading tool instead of having the full content in context.
    """
    if "<attachment" not in text:
        return text

    uploads_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    def _save(m: re.Match[str]) -> str:
        fname = m.group(1)
        data = m.group(2).strip()
        dest = uploads_dir / fname
        # Avoid overwriting — append uuid suffix when needed
        if dest.exists():
            stem = dest.stem
            dest = uploads_dir / f"{stem}_{uuid.uuid4().hex[:8]}{dest.suffix}"
        dest.write_text(data, encoding="utf-8")
        notes.append(f"[Attached file saved: {dest}]")
        return ""

    cleaned = _ATTACHMENT_RE.sub(_save, text).strip()
    if notes:
        cleaned = cleaned + "\n" + "\n".join(notes) if cleaned else "\n".join(notes)
    return cleaned


_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"})

_MIME_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def _extract_images(message: ChatMessage, uploads_dir: Path) -> list[str]:
    """Extract image content parts from a multimodal message and save to disk.

    Returns a list of saved file paths suitable for the ``media`` pipeline.
    """
    if isinstance(message.content, str):
        return []

    uploads_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    for part in message.content:
        if part.type != "file" or not part.data or not part.media_type:
            continue
        if part.media_type not in _IMAGE_MIMES:
            continue

        # part.data is a data URI like "data:image/jpeg;base64,/9j/..."
        data_str = part.data
        if data_str.startswith("data:"):
            # Strip the data URI prefix to get raw base64
            _, _, raw = data_str.partition(",")
        else:
            raw = data_str

        ext = _MIME_EXT.get(part.media_type, ".bin")
        filename = f"img_{uuid.uuid4().hex[:12]}{ext}"
        dest = uploads_dir / filename
        dest.write_bytes(base64.b64decode(raw))
        paths.append(str(dest))

    return paths


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """Stream a chat response using the Vercel AI SDK Data Stream Protocol."""
    web_channel = request.app.state.web_channel
    uploads_dir: Path = request.app.state.uploads_dir

    user_messages = [m for m in body.messages if m.role == "user"]
    if not user_messages:
        return JSONResponse(status_code=400, content={"error": "No user message provided"})

    last_user = user_messages[-1]
    content = last_user.get_text()

    # Strip inline <attachment> blocks — save files to disk instead
    content = _strip_attachments(content, uploads_dir)

    # Extract image attachments from multimodal content parts
    media = _extract_images(last_user, uploads_dir)

    thread_id = body.thread_id or str(uuid.uuid4())

    async def event_generator():
        async for event in stream_agent_response(
            web_channel, thread_id, content, media=media or None
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Thread-Id": thread_id,
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
