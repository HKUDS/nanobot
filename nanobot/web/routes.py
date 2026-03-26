"""FastAPI route definitions for the web chat API."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from loguru import logger
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
        fname = Path(m.group(1)).name  # SEC-07: strip any path components to prevent traversal
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


def _decode_data_uri(data_str: str) -> bytes:
    """Decode a data URI (or raw base64) to bytes."""
    if data_str.startswith("data:"):
        _, _, raw = data_str.partition(",")
    else:
        raw = data_str
    return base64.b64decode(raw)


def _load_manifest(uploads_dir: Path) -> dict[str, str]:
    """Load the hash-to-filename manifest from disk."""
    manifest_path = uploads_dir / ".manifest.json"
    if manifest_path.exists():
        try:
            result: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))
            return result
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_manifest(uploads_dir: Path, manifest: dict[str, str]) -> None:
    """Persist the hash-to-filename manifest to disk."""
    manifest_path = uploads_dir / ".manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _save_upload(data: bytes, filename: str, uploads_dir: Path) -> Path:
    """Save upload data with content-hash deduplication.

    If identical content already exists (by SHA-256), return the existing path
    instead of writing a new copy. Path traversal in *filename* is stripped.
    """
    uploads_dir.mkdir(parents=True, exist_ok=True)

    content_hash = hashlib.sha256(data).hexdigest()
    manifest = _load_manifest(uploads_dir)

    # Check for existing file with same content
    if content_hash in manifest:
        existing = uploads_dir / manifest[content_hash]
        if existing.exists():
            return existing
        # Stale manifest entry — remove it
        del manifest[content_hash]

    # Sanitise filename: strip path components (SEC-07)
    safe_name = Path(filename).name or f"upload_{uuid.uuid4().hex[:12]}.bin"
    dest = uploads_dir / safe_name
    if dest.exists():
        stem = dest.stem
        dest = uploads_dir / f"{stem}_{uuid.uuid4().hex[:8]}{dest.suffix}"

    dest.write_bytes(data)
    manifest[content_hash] = dest.name
    _save_manifest(uploads_dir, manifest)
    return dest


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

        ext = _MIME_EXT.get(part.media_type, ".bin")
        filename = f"img_{uuid.uuid4().hex[:12]}{ext}"
        dest = uploads_dir / filename
        dest.write_bytes(_decode_data_uri(part.data))
        paths.append(str(dest))

    return paths


# Regex to extract the original filename from the companion text marker
# e.g. "[Attached binary file: Copy of DS09247 - 08 - Project Financials.xlsm]"
_ATTACHED_NAME_RE = re.compile(r"\[Attached binary file:\s*(.+?)\]")


def _guess_extension(mime: str) -> str:
    """Map a MIME type to a file extension, using stdlib as fallback."""
    ext = mimetypes.guess_extension(mime, strict=False)
    if ext:
        return ext
    return ".bin"


def _extract_binary_files(message: ChatMessage, uploads_dir: Path) -> list[str]:
    """Extract non-image binary file parts and save to disk.

    Returns a list of ``[Attached file saved: path]`` notes to append to the
    user message so the agent knows where to find the files.
    """
    if isinstance(message.content, str):
        return []

    # Collect original filenames from companion text markers
    original_names: list[str] = []
    for part in message.content:
        if part.type == "text" and part.text:
            m = _ATTACHED_NAME_RE.search(part.text)
            if m:
                original_names.append(m.group(1).strip())

    uploads_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    name_idx = 0

    for part in message.content:
        if part.type != "file" or not part.data or not part.media_type:
            continue
        if part.media_type in _IMAGE_MIMES:
            continue  # handled by _extract_images

        # Use the original filename if available, otherwise generate one
        if name_idx < len(original_names):
            orig = original_names[name_idx]
            name_idx += 1
            # Sanitise: keep only the filename, no path separators
            safe_name = Path(orig).name
            if not safe_name:
                safe_name = f"upload_{uuid.uuid4().hex[:12]}{_guess_extension(part.media_type)}"
            # Avoid overwrites
            dest = uploads_dir / safe_name
            if dest.exists():
                stem = dest.stem
                dest = uploads_dir / f"{stem}_{uuid.uuid4().hex[:8]}{dest.suffix}"
        else:
            ext = _guess_extension(part.media_type)
            filename = f"upload_{uuid.uuid4().hex[:12]}{ext}"
            dest = uploads_dir / filename

        dest.write_bytes(_decode_data_uri(part.data))
        notes.append(f"[Attached file saved: {dest}]")

    return notes


@router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """Stream a chat response using the Vercel AI SDK Data Stream Protocol."""
    web_channel = request.app.state.web_channel
    uploads_dir: Path = request.app.state.uploads_dir

    user_messages = [m for m in body.messages if m.role == "user"]
    if not user_messages:
        return JSONResponse(status_code=400, content={"error": "No user message provided"})

    last_user = user_messages[-1]

    # Debug: log the raw content structure to diagnose attachment issues
    if isinstance(last_user.content, list):
        logger.debug(
            "chat: content is list with {} parts: {}",
            len(last_user.content),
            [(p.type, p.media_type, bool(p.data)) for p in last_user.content],
        )
    else:
        logger.debug("chat: content is str (len={})", len(last_user.content))

    content = last_user.get_text()

    # Strip inline <attachment> blocks — save files to disk instead
    content = _strip_attachments(content, uploads_dir)

    # Remove frontend-injected binary file markers (replaced by saved-path notes below)
    content = _ATTACHED_NAME_RE.sub("", content).strip()

    # Extract image attachments from multimodal content parts
    media = _extract_images(last_user, uploads_dir)

    # Extract binary file attachments (xlsx, pdf, etc.) and append notes
    binary_notes = _extract_binary_files(last_user, uploads_dir)
    logger.debug("chat: binary_notes={}", binary_notes)
    if binary_notes:
        content = content + "\n" + "\n".join(binary_notes) if content else "\n".join(binary_notes)

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
