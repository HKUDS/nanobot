"""Signed media helpers for the WebUI HTTP surface."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import mimetypes
import re
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from websockets.http11 import Request as WsRequest
from websockets.http11 import Response

from nanobot.config.paths import get_media_dir
from nanobot.utils.helpers import safe_filename
from nanobot.webui.http_utils import (
    case_insensitive_header as _case_insensitive_header,
)
from nanobot.webui.http_utils import (
    http_error as _http_error,
)
from nanobot.webui.http_utils import (
    http_response as _http_response,
)

MediaDirProvider = Callable[[str | None], Path]
SignedMediaPath = Callable[[Path], dict[str, str] | None]
SignedMediaUrl = Callable[[Path], str | None]


def b64url_encode(data: bytes) -> str:
    """URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    """Reverse of :func:`b64url_encode`; caller handles decode errors."""
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _default_media_dir(channel: str | None = None) -> Path:
    return get_media_dir(channel)


# Allowed MIME types we actually serve from the media endpoint. Anything
# outside this set is degraded to ``application/octet-stream`` so an
# attacker who somehow gets a signed URL for an unexpected file type can't
# trick the browser into sniffing executable content.
_MEDIA_ALLOWED_MIMES: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/svg+xml",
    "video/mp4",
    "video/webm",
    "video/quicktime",
})
_SVG_MEDIA_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox",
    ),
)

_BYTE_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _parse_single_byte_range(range_header: str, size: int) -> tuple[int, int]:
    """Parse a single HTTP byte range for signed media responses."""
    if size <= 0 or "," in range_header:
        raise ValueError("invalid byte range")
    m = _BYTE_RANGE_RE.fullmatch(range_header.strip())
    if m is None:
        raise ValueError("invalid byte range")
    start_text, end_text = m.groups()
    if not start_text and not end_text:
        raise ValueError("invalid byte range")
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("invalid byte range")
        start = max(size - suffix_length, 0)
        end = size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
        if start >= size or start > end:
            raise ValueError("invalid byte range")
        end = min(end, size - 1)
    return start, end


def sign_media_path(
    abs_path: Path,
    *,
    secret: bytes,
    media_dir: MediaDirProvider = _default_media_dir,
) -> str | None:
    """Return a signed ``/api/media/<sig>/<payload>`` URL for a media-root path."""
    try:
        media_root = media_dir(None).resolve()
        rel = abs_path.resolve().relative_to(media_root)
    except (OSError, ValueError):
        return None
    payload = b64url_encode(rel.as_posix().encode("utf-8"))
    mac = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()[:16]
    return f"/api/media/{b64url_encode(mac)}/{payload}"


def sign_or_stage_media_path(
    path: Path,
    *,
    secret: bytes,
    media_dir: MediaDirProvider = _default_media_dir,
    logger: Any | None = None,
) -> dict[str, str] | None:
    """Sign an existing media-root path, or stage an arbitrary file before signing."""
    signed = sign_media_path(path, secret=secret, media_dir=media_dir)
    if signed is not None:
        return {"url": signed, "name": path.name}
    try:
        if not path.is_file():
            return None
        target_dir = media_dir("websocket")
        safe_name = safe_filename(path.name) or "attachment"
        staged = target_dir / f"{uuid.uuid4().hex[:12]}-{safe_name}"
        shutil.copyfile(path, staged)
    except OSError as exc:
        if logger is not None:
            logger.warning("failed to stage outbound media {}: {}", path, exc)
        return None
    signed = sign_media_path(staged, secret=secret, media_dir=media_dir)
    if signed is None:
        return None
    return {"url": signed, "name": path.name}


def media_attachment_kind(name: str) -> str:
    """Infer the WebUI media attachment kind from a filename."""
    mime, _ = mimetypes.guess_type(name)
    if mime and mime.startswith("video/"):
        return "video"
    if mime and mime.startswith("image/"):
        return "image"
    return "file"


def signed_media_attachments(
    paths: list[str],
    *,
    sign_path: SignedMediaPath,
) -> list[dict[str, Any]]:
    """Map persisted media paths to WebUI attachment dicts with fresh signed URLs."""
    out: list[dict[str, Any]] = []
    for pstr in paths:
        path = Path(pstr)
        att = sign_path(path)
        if att is None:
            continue
        url = att.get("url")
        if not url:
            continue
        name = att.get("name") or path.name
        out.append({"kind": media_attachment_kind(name), "url": url, "name": name})
    return out


def attach_signed_media_urls(
    payload: dict[str, Any],
    *,
    sign_path: SignedMediaUrl,
) -> None:
    """Replace raw media path lists in a WebUI session payload with signed URLs."""
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        media = msg.get("media")
        if not isinstance(media, list) or not media:
            continue
        urls: list[dict[str, str]] = []
        for entry in media:
            if not isinstance(entry, str) or not entry:
                continue
            signed = sign_path(Path(entry))
            if signed is None:
                continue
            urls.append({"url": signed, "name": Path(entry).name})
        if urls:
            msg["media_urls"] = urls
        msg.pop("media", None)


def serve_signed_media(
    sig: str,
    payload: str,
    *,
    secret: bytes,
    request: WsRequest | None = None,
    media_dir: MediaDirProvider = _default_media_dir,
) -> Response:
    """Serve a signed media URL, including browser-friendly byte ranges."""
    try:
        provided_mac = b64url_decode(sig)
    except (ValueError, binascii.Error):
        return _http_error(401, "invalid signature")
    expected_mac = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(expected_mac, provided_mac):
        return _http_error(401, "invalid signature")
    try:
        rel_bytes = b64url_decode(payload)
        rel_str = rel_bytes.decode("utf-8")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return _http_error(400, "invalid payload")
    try:
        media_root = media_dir(None).resolve()
        candidate = (media_root / rel_str).resolve()
        candidate.relative_to(media_root)
    except (OSError, ValueError):
        return _http_error(404, "not found")
    if not candidate.is_file():
        return _http_error(404, "not found")

    mime, _ = mimetypes.guess_type(candidate.name)
    if mime not in _MEDIA_ALLOWED_MIMES:
        mime = "application/octet-stream"
    common_headers = [
        ("Accept-Ranges", "bytes"),
        ("Cache-Control", "private, max-age=31536000, immutable"),
        ("X-Content-Type-Options", "nosniff"),
    ]
    if mime == "image/svg+xml":
        common_headers.extend(_SVG_MEDIA_HEADERS)
    try:
        size = candidate.stat().st_size
    except OSError:
        return _http_error(500, "read error")

    range_header = _case_insensitive_header(request.headers, "Range") if request else ""
    if range_header:
        try:
            start, end = _parse_single_byte_range(range_header, size)
        except ValueError:
            return _http_response(
                b"range not satisfiable",
                status=416,
                extra_headers=[
                    ("Accept-Ranges", "bytes"),
                    ("Content-Range", f"bytes */{size}"),
                    ("X-Content-Type-Options", "nosniff"),
                ],
            )
        try:
            length = end - start + 1
            with candidate.open("rb") as fh:
                fh.seek(start)
                body = fh.read(length)
        except OSError:
            return _http_error(500, "read error")
        return _http_response(
            body,
            status=206,
            content_type=mime,
            extra_headers=[
                *common_headers,
                ("Content-Range", f"bytes {start}-{end}/{size}"),
            ],
        )

    try:
        body = candidate.read_bytes()
    except OSError:
        return _http_error(500, "read error")
    return _http_response(body, content_type=mime, extra_headers=common_headers)
