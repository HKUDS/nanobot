"""Data-URL persistence for API uploads and audio transcription.

Binary WebUI uploads share the media filename layout through ``media_destination``.
"""

from __future__ import annotations

import base64
import mimetypes
import uuid
from pathlib import Path

from nanobot.utils.helpers import safe_filename

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
MAX_FILE_SIZE = DEFAULT_MAX_BYTES

_MIME_EXTENSION_OVERRIDES = {
    # Python's ``mimetypes`` maps browser-recorded audio/webm to ``.weba`` and
    # audio/ogg to ``.oga`` on macOS. Some transcription APIs validate by the
    # file extension and accept the canonical container extensions instead.
    "application/ogg": ".ogg",
    "audio/ogg": ".ogg",
    "audio/mpga": ".mpga",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    "audio/x-m4a": ".m4a",
    "audio/x-wav": ".wav",
    "audio/vnd.wave": ".wav",
    "video/webm": ".webm",
    "application/json": ".json",
    "application/pdf": ".pdf",
    "application/toml": ".toml",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/x-yaml": ".yaml",
    "application/xhtml+xml": ".html",
    "application/xml": ".xml",
    "application/yaml": ".yaml",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/xml": ".xml",
    "text/yaml": ".yaml",
}


class FileSizeExceededError(Exception):
    """Raised when a decoded payload exceeds the caller's size limit."""


FileSizeExceeded = FileSizeExceededError


def save_base64_data_url(
    data_url: str,
    media_dir: Path,
    *,
    max_bytes: int | None = None,
    filename: str | None = None,
) -> str | None:
    """Decode a ``data:<mime>;base64,<payload>`` URL and persist it.

    Returns the absolute path on success, ``None`` when the URL shape or the
    base64 payload itself is malformed. Raises :class:`FileSizeExceeded`
    when the decoded payload is larger than ``max_bytes`` (default 10 MB).
    """
    # Parse delimiters directly so malformed MIME parameters cannot trigger regex backtracking.
    header, separator, b64_payload = data_url.partition(",")
    if not separator or header[:5].lower() != "data:" or header[-7:].lower() != ";base64":
        return None
    mime_type = header[5:-7].partition(";")[0]
    if not mime_type:
        return None
    mime_type = mime_type.strip().lower()
    try:
        raw = base64.b64decode(b64_payload, validate=True)
    except Exception:
        return None
    if not raw:
        return None
    limit = DEFAULT_MAX_BYTES if max_bytes is None else max_bytes
    if len(raw) > limit:
        raise FileSizeExceeded(f"File exceeds {limit // (1024 * 1024)}MB limit")
    dest = media_destination(media_dir, mime_type, filename=filename)
    dest.write_bytes(raw)
    return str(dest)


def media_destination(media_dir: Path, mime_type: str, *, filename: str | None = None) -> Path:
    """Choose the shared media layout for binary and data-URL ingress."""
    ext = _MIME_EXTENSION_OVERRIDES.get(mime_type) or mimetypes.guess_extension(mime_type) or ".bin"
    base = safe_filename(filename or "")
    stem = Path(base).stem[:80] if base else ""
    # Leave room for the 12-character ID, separator, and extension.
    max_stem_bytes = 255 - 13 - len(ext.encode("utf-8"))
    stem = stem.encode("utf-8")[:max_stem_bytes].decode("utf-8", errors="ignore")
    saved_name = f"{uuid.uuid4().hex[:12]}_{stem}{ext}" if stem else f"{uuid.uuid4().hex[:12]}{ext}"
    return media_dir / safe_filename(saved_name)
