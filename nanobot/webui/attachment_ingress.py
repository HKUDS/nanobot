"""MIME and count policy for binary HTTP attachment ingress."""

MAX_VIDEOS_PER_MESSAGE = 1
MAX_VIDEO_BYTES = 20 * 1024 * 1024

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
