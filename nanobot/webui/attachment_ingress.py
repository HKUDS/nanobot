"""Validation and persistence for inbound WebUI message attachments."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from nanobot.utils.media_decode import FileSizeExceeded, save_base64_data_url

AttachmentRejection = Literal[
    "malformed",
    "too_many_images",
    "too_many_videos",
    "too_many_attachments",
    "mime",
    "size",
    "decode",
]
AttachmentIngressResult = tuple[list[str], AttachmentRejection | None]

_MAX_IMAGES_PER_MESSAGE = 4
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_VIDEOS_PER_MESSAGE = 1
_MAX_VIDEO_BYTES = 20 * 1024 * 1024
_MAX_ATTACHMENTS_PER_MESSAGE = 4
_MAX_DOCUMENT_BYTES = 8 * 1024 * 1024

_IMAGE_MIME_ALLOWED: frozenset[str] = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})

_VIDEO_MIME_ALLOWED: frozenset[str] = frozenset({
    "video/mp4",
    "video/webm",
    "video/quicktime",
})

_DOCUMENT_MIME_ALLOWED: frozenset[str] = frozenset({
    "application/json",
    "application/pdf",
    "application/toml",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/x-yaml",
    "application/xhtml+xml",
    "application/xml",
    "application/yaml",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/xml",
    "text/yaml",
})

_UPLOAD_MIME_ALLOWED: frozenset[str] = (
    _IMAGE_MIME_ALLOWED | _VIDEO_MIME_ALLOWED | _DOCUMENT_MIME_ALLOWED
)

_DATA_URL_MIME_RE = re.compile(r"^data:([^;,]+)(?:;[^,]*)*;base64,", re.DOTALL)


def extract_data_url_mime(url: Any) -> str | None:
    """Return the normalized MIME from a base64 data URL, else ``None``."""
    if not isinstance(url, str):
        return None
    match = _DATA_URL_MIME_RE.match(url)
    if match is None:
        return None
    return match.group(1).strip().lower() or None


def store_inbound_attachments(
    media: list[Any],
    *,
    media_dir: Path,
    logger: Any,
) -> AttachmentIngressResult:
    """Validate and atomically persist one WebUI message's attachments.

    The caller owns transport-level error mapping. This function owns the
    WebUI upload policy and removes files already written when a later item
    makes the batch invalid.
    """
    image_count = 0
    video_count = 0
    document_count = 0
    for item in media:
        mime = (
            extract_data_url_mime(item.get("data_url", ""))
            if isinstance(item, dict)
            else None
        )
        if mime in _VIDEO_MIME_ALLOWED:
            video_count += 1
        elif mime in _IMAGE_MIME_ALLOWED:
            image_count += 1
        elif mime in _DOCUMENT_MIME_ALLOWED:
            document_count += 1
    if image_count > _MAX_IMAGES_PER_MESSAGE:
        return [], "too_many_images"
    if video_count > _MAX_VIDEOS_PER_MESSAGE:
        return [], "too_many_videos"
    if image_count + document_count > _MAX_ATTACHMENTS_PER_MESSAGE:
        return [], "too_many_attachments"

    paths: list[str] = []

    def abort(reason: AttachmentRejection) -> AttachmentIngressResult:
        for path in paths:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("failed to unlink partial media {}: {}", path, exc)
        return [], reason

    for item in media:
        if not isinstance(item, dict):
            return abort("malformed")
        data_url = item.get("data_url")
        if not isinstance(data_url, str) or not data_url:
            return abort("malformed")
        mime = extract_data_url_mime(data_url)
        if mime is None:
            return abort("decode")
        if mime not in _UPLOAD_MIME_ALLOWED:
            return abort("mime")
        is_video = mime in _VIDEO_MIME_ALLOWED
        is_document = mime in _DOCUMENT_MIME_ALLOWED
        max_bytes = (
            _MAX_VIDEO_BYTES if is_video
            else _MAX_DOCUMENT_BYTES if is_document
            else _MAX_IMAGE_BYTES
        )
        name = (
            item.get("name")
            if is_document and isinstance(item.get("name"), str)
            else None
        )
        try:
            saved = save_base64_data_url(
                data_url,
                media_dir,
                max_bytes=max_bytes,
                filename=name,
            )
        except FileSizeExceeded:
            return abort("size")
        except Exception as exc:
            logger.warning("media decode failed: {}", exc)
            return abort("decode")
        if saved is None:
            return abort("decode")
        paths.append(saved)
    return paths, None
