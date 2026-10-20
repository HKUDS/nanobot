"""Shared MIME and batch limits for WebSocket attachment ingress."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AttachmentIngressLimits:
    max_count: int = 4
    max_file_bytes: int = 6 * 1024 * 1024
    max_total_bytes: int = 24 * 1024 * 1024


MAX_VIDEOS_PER_MESSAGE = 1
MAX_VIDEO_BYTES = 20 * 1024 * 1024

# A 20 MiB upload takes about 168 seconds at 1 Mbps. Keep a finite total
# budget with room for contention, but release stalled uploads promptly.
UPLOAD_TIMEOUT_SECONDS = 300.0
UPLOAD_IDLE_TIMEOUT_SECONDS = 30.0
UPLOAD_REQUEST_TIMEOUT_SECONDS = 315.0

IMAGE_MIME_ALLOWED: frozenset[str] = frozenset({
    "image/png", "image/jpeg", "image/webp", "image/gif",
})
VIDEO_MIME_ALLOWED: frozenset[str] = frozenset({
    "video/mp4", "video/webm", "video/quicktime",
})
DOCUMENT_MIME_ALLOWED: frozenset[str] = frozenset({
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
    "text/csv", "text/html", "text/markdown", "text/plain", "text/xml", "text/yaml",
})
UPLOAD_MIME_ALLOWED = IMAGE_MIME_ALLOWED | VIDEO_MIME_ALLOWED | DOCUMENT_MIME_ALLOWED


def validate_attachment_batch(
    items: list[tuple[str, int]], *, limits: AttachmentIngressLimits,
) -> None:
    """Apply the same per-message limits to uploads and borrowed local files."""
    videos = sum(mime in VIDEO_MIME_ALLOWED for mime, _ in items)
    if videos > MAX_VIDEOS_PER_MESSAGE or len(items) - videos > limits.max_count:
        raise ValueError("Too many attachments")
    for mime, size in items:
        if mime not in UPLOAD_MIME_ALLOWED:
            raise ValueError("Unsupported attachment MIME")
        limit = MAX_VIDEO_BYTES if mime in VIDEO_MIME_ALLOWED else limits.max_file_bytes
        if not 0 < size <= limit:
            raise ValueError("Invalid attachment size")
    if sum(size for mime, size in items if mime not in VIDEO_MIME_ALLOWED) > limits.max_total_bytes:
        raise ValueError("Attachment total exceeds limit")
