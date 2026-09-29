"""Bounded staging for binary uploads, independent of WebSocket frame limits.

The HTTP adapter must authenticate before calling ``upload``. ``owner`` must be
server-authenticated identity, never a client-selected ID. References are only
transport state; callers persist the paths returned by ``resolve`` as before.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path

from nanobot.utils.media_decode import media_destination
from nanobot.webui.attachment_ingress import (
    DOCUMENT_MIME_ALLOWED,
    IMAGE_MIME_ALLOWED,
    MAX_VIDEO_BYTES,
    MAX_VIDEOS_PER_MESSAGE,
    UPLOAD_MIME_ALLOWED,
    VIDEO_MIME_ALLOWED,
)
from nanobot.webui.ingress_policy import AttachmentIngressLimits


class AttachmentUploadError(ValueError):
    """An upload or reference failed validation without consuming the draft."""


@dataclass(frozen=True)
class _Attachment:
    owner: str
    path: Path
    mime: str
    size: int
    expires: float


class AttachmentStore:
    """Single-event-loop staging store with disk, count, and lifetime bounds.

    A whole file's declared size is reserved before awaiting its first chunk,
    so concurrent slow uploads cannot bypass the global disk quota. ``prune``
    should also be called periodically by the owning gateway. Committed files
    leave this store and are managed by the existing session media lifecycle.
    """

    def __init__(
        self,
        media_dir: Path,
        *,
        limits: AttachmentIngressLimits | None = None,
        max_pending: int = 128,
        max_pending_bytes: int = 128 * 1024 * 1024,
        ttl_seconds: float = 600,
        upload_timeout: float = 60,
    ) -> None:
        if min(max_pending, max_pending_bytes, ttl_seconds, upload_timeout) <= 0:
            raise ValueError("Attachment store bounds must be positive")
        self.media_dir = media_dir
        self.limits = limits or AttachmentIngressLimits()
        self.max_pending = max_pending
        self.max_pending_bytes = max_pending_bytes
        self.ttl_seconds = ttl_seconds
        self.upload_timeout = upload_timeout
        self._entries: dict[str, _Attachment] = {}
        self._reserved_bytes = 0
        self._active = 0

    async def upload(
        self,
        chunks: AsyncIterable[bytes],
        *,
        owner: str,
        mime: str,
        size: int,
        filename: str | None = None,
    ) -> str:
        """Stream a declared-length binary body and return an opaque reference.

        No body bytes are requested until metadata and capacity are validated.
        The adapter must disable automatic request decompression and reject
        ambiguous framing, and must not buffer the complete body beforehand.
        """
        self.prune()
        if not owner:
            raise AttachmentUploadError("Missing authenticated owner")
        if mime not in UPLOAD_MIME_ALLOWED:
            raise AttachmentUploadError("Unsupported attachment MIME")
        limit = MAX_VIDEO_BYTES if mime in VIDEO_MIME_ALLOWED else self.limits.max_file_bytes
        if isinstance(size, bool) or not 0 < size <= limit:
            raise AttachmentUploadError("Invalid attachment size")
        if self._active + len(self._entries) >= self.max_pending:
            raise AttachmentUploadError("Too many pending attachments")
        if self._reserved_bytes + size > self.max_pending_bytes:
            raise AttachmentUploadError("Pending attachment storage is full")
        self._active += 1
        self._reserved_bytes += size
        path: Path | None = None
        stored = False
        created = False
        try:
            self.media_dir.mkdir(parents=True, exist_ok=True)
            path = media_destination(
                self.media_dir, mime,
                filename=filename if mime in DOCUMENT_MIME_ALLOWED else None,
            )
            received = 0
            # Exclusive creation prevents accidental overwrite or symlink following.
            with path.open("xb") as output:
                created = True
                async with asyncio.timeout(self.upload_timeout):
                    async for chunk in chunks:
                        received += len(chunk)
                        if received > size:
                            raise AttachmentUploadError("Attachment exceeds declared size")
                        output.write(chunk)
            if received != size:
                raise AttachmentUploadError("Incomplete attachment body")
            reference = secrets.token_urlsafe(32)
            self._entries[reference] = _Attachment(
                owner, path, mime, size, time.monotonic() + self.ttl_seconds,
            )
            stored = True
            return reference
        finally:
            self._active -= 1
            if not stored:
                self._reserved_bytes -= size
                if created and path is not None:
                    path.unlink(missing_ok=True)

    def resolve(self, references: list[str], *, owner: str) -> list[str]:
        """Validate a complete batch without consuming it, allowing send retries."""
        self.prune()
        if len(references) > self.limits.max_count + MAX_VIDEOS_PER_MESSAGE:
            raise AttachmentUploadError("Too many attachments")
        if len(set(references)) != len(references):
            raise AttachmentUploadError("Duplicate attachment reference")
        entries: list[_Attachment] = []
        for reference in references:
            entry = self._entries.get(reference)
            if entry is None or not owner or entry.owner != owner:
                raise AttachmentUploadError("Invalid attachment reference")
            entries.append(entry)
        videos = sum(entry.mime in VIDEO_MIME_ALLOWED for entry in entries)
        images = sum(entry.mime in IMAGE_MIME_ALLOWED for entry in entries)
        if videos > MAX_VIDEOS_PER_MESSAGE or images > self.limits.max_count:
            raise AttachmentUploadError("Too many attachments")
        if len(entries) - videos > self.limits.max_count:
            raise AttachmentUploadError("Too many attachments")
        if sum(e.size for e in entries if e.mime not in VIDEO_MIME_ALLOWED) > self.limits.max_total_bytes:
            raise AttachmentUploadError("Attachment total exceeds limit")
        return [str(entry.path) for entry in entries]

    def commit(self, references: list[str], *, owner: str) -> list[str]:
        """Transfer validated files to session ownership after message acceptance.

        The caller must not await between resolve, synchronous acceptance, and
        commit. A rejected message must leave references staged for retry.
        """
        paths = self.resolve(references, owner=owner)
        for reference in references:
            self._reserved_bytes -= self._entries.pop(reference).size
        return paths

    def prune(self) -> None:
        """Remove abandoned uploads; never delete committed session media."""
        now = time.monotonic()
        for reference, entry in list(self._entries.items()):
            if entry.expires <= now:
                entry.path.unlink(missing_ok=True)
                self._reserved_bytes -= entry.size
                del self._entries[reference]

    def clear(self) -> None:
        """Clean staging after the gateway has stopped accepting uploads."""
        if self._active:
            raise RuntimeError("Stop active uploads before clearing attachment storage")
        for reference, entry in list(self._entries.items()):
            entry.path.unlink(missing_ok=True)
            self._reserved_bytes -= entry.size
            del self._entries[reference]
