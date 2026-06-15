"""Workspace-scoped file listing for the WebUI."""

from __future__ import annotations

import base64 as _base64
import mimetypes
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_FILE_PREVIEW_BYTES = 512 * 1024
MAX_DIR_ENTRIES = 500
MAX_CHUNK_B64_BYTES = 1024

_upload_sessions: dict[str, "UploadSession"] = {}


@dataclass
class UploadSession:
    upload_id: str
    filename: str
    target_path: Path
    total_chunks: int
    chunks: dict[int, bytes] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)


def upload_init_payload(
    workspace_path: Path,
    raw_path: str,
    filename: str,
    total_chunks: int,
) -> dict[str, Any]:
    target_dir = (workspace_path / raw_path.lstrip("/")).resolve()
    if not target_dir.is_relative_to(workspace_path):
        return _error_payload(403, "Path is outside the workspace")

    upload_id = secrets.token_urlsafe(16)
    _upload_sessions[upload_id] = UploadSession(
        upload_id=upload_id,
        filename=filename,
        target_path=target_dir,
        total_chunks=total_chunks,
    )
    return {"ok": True, "upload_id": upload_id, "total_chunks": total_chunks}


def upload_chunk_payload(
    upload_id: str,
    chunk_index: int,
    chunk_b64: str,
) -> dict[str, Any]:
    session = _upload_sessions.get(upload_id)
    if session is None:
        return _error_payload(404, "Upload session not found")
    if chunk_index < 0 or chunk_index >= session.total_chunks:
        return _error_payload(400, "Invalid chunk index")
    if len(chunk_b64) > MAX_CHUNK_B64_BYTES:
        return _error_payload(413, f"Chunk too large. Maximum is {MAX_CHUNK_B64_BYTES} base64 bytes.")

    try:
        chunk_data = _base64.b64decode(chunk_b64, validate=True)
    except Exception:
        return _error_payload(400, "Invalid base64 chunk")

    session.chunks[chunk_index] = chunk_data
    received = len(session.chunks)
    return {"ok": True, "upload_id": upload_id, "chunk_index": chunk_index, "received": received, "total": session.total_chunks}


def upload_finalize_payload(upload_id: str) -> dict[str, Any]:
    session = _upload_sessions.pop(upload_id, None)
    if session is None:
        return _error_payload(404, "Upload session not found")

    if len(session.chunks) != session.total_chunks:
        missing = set(range(session.total_chunks)) - set(session.chunks.keys())
        return _error_payload(400, f"Missing chunks: {sorted(missing)}")

    try:
        full_content = b"".join(session.chunks[i] for i in range(session.total_chunks))
        target = session.target_path / session.filename
        if not target.is_relative_to(session.target_path):
            return _error_payload(403, "Invalid filename")
        session.target_path.mkdir(parents=True, exist_ok=True)
        target.write_bytes(full_content)
    except OSError as e:
        return _error_payload(500, f"Failed to write file: {e}")

    return {"ok": True, "path": str(target), "size": len(full_content)}

EXCLUDED_NAMES = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    "dist",
    "build",
    ".egg-info",
    ".DS_Store",
    "Thumbs.db",
}

EXCLUDED_PREFIXES = (".",)


def _is_hidden(name: str) -> bool:
    if name in EXCLUDED_NAMES:
        return True
    for prefix in EXCLUDED_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def _sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(entry: dict[str, Any]) -> tuple[int, str]:
        if entry["is_dir"]:
            return (0, entry["name"].lower())
        return (1, entry["name"].lower())

    return sorted(entries, key=key)


def files_list_payload(
    workspace_path: Path,
    raw_path: str | None = None,
) -> dict[str, Any]:
    """Return directory entries for a path inside the workspace."""
    if raw_path is None:
        target = workspace_path
    else:
        target = (workspace_path / raw_path.lstrip("/")).resolve()

    if not target.exists():
        return _error_payload(404, "Directory not found")
    if not target.is_dir():
        return _error_payload(400, "Path is not a directory")
    if not target.is_relative_to(workspace_path):
        return _error_payload(403, "Path is outside the workspace")

    try:
        raw_entries = os.scandir(target)
    except OSError:
        return _error_payload(403, "Cannot read directory")

    entries: list[dict[str, Any]] = []
    count = 0
    for entry in raw_entries:
        if _is_hidden(entry.name):
            continue
        if count >= MAX_DIR_ENTRIES:
            break
        try:
            stat = entry.stat()
            rel = target / entry.name
            entries.append(
                {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if not entry.is_dir() else 0,
                    "mtime": stat.st_mtime,
                }
            )
            count += 1
        except OSError:
            continue

    display_path = _relative_path(target, workspace_path)
    return {
        "path": str(target),
        "display_path": display_path,
        "workspace_path": str(workspace_path),
        "entries": _sort_entries(entries),
        "has_more": count >= MAX_DIR_ENTRIES,
    }


def file_content_payload(
    workspace_path: Path,
    raw_path: str,
) -> dict[str, Any]:
    """Return the content of a file inside the workspace."""
    target = (workspace_path / raw_path.lstrip("/")).resolve()

    if not target.exists():
        return _error_payload(404, "File not found")
    if not target.is_file():
        return _error_payload(400, "Path is not a file")
    if not target.is_relative_to(workspace_path):
        return _error_payload(403, "Path is outside the workspace")

    size = target.stat().st_size
    if size > MAX_FILE_PREVIEW_BYTES:
        return _error_payload(413, f"File is too large ({size} bytes). Maximum is {MAX_FILE_PREVIEW_BYTES} bytes.")

    try:
        with open(target, "rb") as f:
            raw = f.read(MAX_FILE_PREVIEW_BYTES + 1)
    except OSError:
        return _error_payload(500, "Failed to read file")

    if b"\0" in raw[:4096]:
        return _error_payload(415, "Binary files cannot be previewed as text")

    truncated = len(raw) > MAX_FILE_PREVIEW_BYTES
    preview_bytes = raw[:MAX_FILE_PREVIEW_BYTES]

    try:
        content = preview_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = preview_bytes.decode("utf-8", errors="replace")

    mime = mimetypes.guess_type(str(target))[0]
    return {
        "path": str(target),
        "display_path": _relative_path(target, workspace_path),
        "language": _language_for_path(target),
        "mime": mime,
        "content": content,
        "size": size,
        "truncated": truncated,
    }


MAX_DOWNLOAD_SIZE_BYTES = 64 * 1024 * 1024
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024


def file_download_info(
    workspace_path: Path,
    raw_path: str,
) -> tuple[dict[str, Any], bytes | None]:
    """Return file metadata and bytes for download. Bytes may be None on error."""
    target = (workspace_path / raw_path.lstrip("/")).resolve()

    if not target.exists():
        return (_error_payload(404, "File not found"), None)
    if not target.is_file():
        return (_error_payload(400, "Path is not a file"), None)
    if not target.is_relative_to(workspace_path):
        return (_error_payload(403, "Path is outside the workspace"), None)

    try:
        raw = target.read_bytes()
    except OSError:
        return (_error_payload(500, "Failed to read file"), None)

    size = len(raw)
    if size > MAX_DOWNLOAD_SIZE_BYTES:
        return (_error_payload(413, f"File too large ({size} bytes). Maximum is {MAX_DOWNLOAD_SIZE_BYTES} bytes."), None)

    meta = {
        "name": target.name,
        "size": size,
        "mime": mimetypes.guess_type(str(target))[0] or "application/octet-stream",
    }
    return (meta, raw)


def file_delete_payload(
    workspace_path: Path,
    raw_path: str,
) -> dict[str, Any]:
    """Delete a file or empty directory inside the workspace."""
    target = (workspace_path / raw_path.lstrip("/")).resolve()

    if not target.exists():
        return _error_payload(404, "Path not found")
    if not target.is_relative_to(workspace_path):
        return _error_payload(403, "Path is outside the workspace")

    try:
        if target.is_dir():
            if any(target.iterdir()):
                return _error_payload(409, "Directory is not empty")
            target.rmdir()
        else:
            target.unlink()
    except OSError as e:
        return _error_payload(500, f"Failed to delete: {e}")

    return {"ok": True, "deleted": str(target)}


def file_upload_payload(
    workspace_path: Path,
    raw_path: str,
    content_b64: str,
    filename: str,
) -> dict[str, Any]:
    """Save a file (base64-encoded content) inside the workspace."""
    if len(content_b64) > MAX_UPLOAD_SIZE_BYTES * 4 // 3:
        return _error_payload(413, f"File too large. Maximum size is {MAX_UPLOAD_SIZE_BYTES} bytes.")

    try:
        content = _base64.b64decode(content_b64, validate=True)
    except Exception:
        return _error_payload(400, "Invalid base64 content")

    target_dir = (workspace_path / raw_path.lstrip("/")).resolve()
    if not target_dir.is_relative_to(workspace_path):
        return _error_payload(403, "Path is outside the workspace")

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        if not target.is_relative_to(target_dir):
            return _error_payload(403, "Invalid filename")
        target.write_bytes(content)
    except OSError as e:
        return _error_payload(500, f"Failed to write file: {e}")

    return {"ok": True, "path": str(target), "size": len(content)}


def file_save_payload(
    workspace_path: Path,
    raw_path: str,
    content: str,
) -> dict[str, Any]:
    """Save text content to a file inside the workspace."""
    target = (workspace_path / raw_path.lstrip("/")).resolve()

    if not target.is_relative_to(workspace_path):
        return _error_payload(403, "Path is outside the workspace")

    try:
        target.write_text(content, encoding="utf-8")
    except OSError as e:
        return _error_payload(500, f"Failed to save file: {e}")

    return {"ok": True, "path": str(target), "size": len(content.encode("utf-8"))}


def _error_payload(status: int, message: str) -> dict[str, Any]:
    return {"error": message, "status": status}


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _language_for_path(path: Path) -> str:
    name = path.name.lower()
    ext = path.suffix.lower().lstrip(".")
    if name == "dockerfile":
        return "dockerfile"
    return {
        "cjs": "javascript",
        "css": "css",
        "cts": "typescript",
        "html": "html",
        "js": "javascript",
        "json": "json",
        "jsonl": "json",
        "jsx": "jsx",
        "md": "markdown",
        "mdx": "markdown",
        "mjs": "javascript",
        "mts": "typescript",
        "py": "python",
        "pyi": "python",
        "scss": "scss",
        "sh": "bash",
        "toml": "toml",
        "ts": "typescript",
        "tsx": "tsx",
        "yaml": "yaml",
        "yml": "yaml",
        "txt": "text",
        "rs": "rust",
        "go": "go",
        "java": "java",
        "c": "c",
        "cpp": "cpp",
        "h": "c",
        "hpp": "cpp",
        "css": "css",
        "less": "less",
        "svg": "xml",
        "xml": "xml",
        "sql": "sql",
    }.get(ext, ext or "text")
