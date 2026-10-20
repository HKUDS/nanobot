"""Read-only local attachment checks shared by WebUI and native TUI ingress."""

from __future__ import annotations

import mimetypes
import os
import stat
from typing import Literal, TypedDict

from nanobot.channels.websocket.attachment_policy import (
    AttachmentIngressLimits,
    validate_attachment_batch,
)
from nanobot.security.workspace_access import WorkspaceScope
from nanobot.webui.file_preview import WebUIFilePreviewError, resolve_file_path


class LocalAttachment(TypedDict):
    path: str
    name: str
    size: int
    mime: str
    kind: Literal["image", "video", "file"]


# Match the upload ingress formats even on hosts with different MIME registries.
_MIME_BY_SUFFIX = {
    ".md": "text/markdown", ".log": "text/plain", ".txt": "text/plain",
    ".ini": "text/plain", ".cfg": "text/plain", ".csv": "text/csv",
    ".yaml": "application/yaml", ".yml": "application/yaml", ".toml": "application/toml",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
}


def inspect_local_attachment(
    path: str, *, scope: WorkspaceScope, limits: AttachmentIngressLimits,
) -> LocalAttachment:
    """Check accessibility and metadata without reading or copying the file body."""
    resolved = resolve_file_path(path, scope=scope, literal=True)
    try:
        fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise WebUIFilePreviewError(400, "attachment must be a regular file")
        finally:
            os.close(fd)
    except PermissionError as exc:
        raise WebUIFilePreviewError(403, "file is not readable") from exc
    except OSError as exc:
        raise WebUIFilePreviewError(404, "file is unavailable") from exc
    mime = _MIME_BY_SUFFIX.get(resolved.suffix.lower()) or mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    try:
        validate_attachment_batch([(mime, info.st_size)], limits=limits)
    except ValueError as exc:
        raise WebUIFilePreviewError(400, str(exc)) from exc
    kind = "video" if mime.startswith("video/") else "image" if mime.startswith("image/") else "file"
    return {"path": str(resolved), "name": resolved.name, "size": info.st_size, "mime": mime, "kind": kind}
