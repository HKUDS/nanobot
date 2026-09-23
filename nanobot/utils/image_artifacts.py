"""Typed image outputs and connection-owned, non-durable image storage."""

from __future__ import annotations

import base64
import tempfile
from dataclasses import dataclass
from pathlib import Path

from nanobot.events import AgentEvent

MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_TURN_IMAGES = 32
_TEMP_IMAGE_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ImageArtifact:
    id: str
    path: str
    mime: str
    source: str


class ImageArtifactResult(str):
    """A tool observation with explicitly user-facing, trusted artifact references."""

    artifacts: tuple[ImageArtifact, ...]

    def __new__(cls, content: str, artifacts: tuple[ImageArtifact, ...]) -> ImageArtifactResult:
        result = super().__new__(cls, content)
        result.artifacts = artifacts
        return result

    def __reduce__(self) -> tuple[type[str], tuple[str]]:
        # Runtime-only references must not enter copied model history or persisted sessions.
        return str, (str(self),)


@dataclass(frozen=True)
class ImageArtifactsEvent(AgentEvent):
    artifacts: tuple[ImageArtifact, ...]
    tool_call_id: str


class EphemeralImageStore:
    """Private files retained only by the owning temporary chat, never signed publicly.

    Closing is terminal: a late tool completion cannot recreate the directory.
    The store owns only its own files, never exports or user workspace files.
    """

    def __init__(self) -> None:
        self._directory: tempfile.TemporaryDirectory[str] | None = None
        self._files: dict[str, str] = {}
        self._bytes = 0
        self._closed = False

    def store(self, artifact_id: str, raw: bytes, mime: str, extension: str) -> Path:
        if self._closed:
            raise ValueError("temporary image storage is closed")
        # Base64 must fit the existing 8 MiB WebSocket outbound-frame budget.
        if len(raw) > _TEMP_IMAGE_BYTES:
            raise ValueError("temporary image exceeds the 4 MiB delivery limit")
        if self._bytes + len(raw) > 64 * 1024 * 1024:
            raise ValueError("temporary image storage limit reached (64 MiB per chat)")
        if len(self._files) >= 32:
            raise ValueError("temporary image count limit reached")
        if self._directory is None:
            self._directory = tempfile.TemporaryDirectory(prefix="nanobot-images-")
        # Neither segment is accepted from a tool caller.
        if not artifact_id.startswith("img_") or not artifact_id[4:].isalnum():
            raise ValueError("invalid image identity")
        if extension not in {".png", ".jpg", ".gif", ".webp"}:
            raise ValueError("invalid image extension")
        path = Path(self._directory.name).resolve() / f"{artifact_id}{extension}"
        path.write_bytes(raw)
        self._files[str(path)] = mime
        self._bytes += len(raw)
        return path

    def contains(self, path: str) -> bool:
        try:
            return not self._closed and str(Path(path).resolve()) in self._files
        except (OSError, ValueError):
            return False

    def attachment(self, path: str) -> dict[str, str] | None:
        if not self.contains(path):
            return None
        path = str(Path(path).resolve())
        try:
            with Path(path).open("rb") as image:
                raw = image.read(_TEMP_IMAGE_BYTES + 1)
        except OSError:
            return None
        if len(raw) > _TEMP_IMAGE_BYTES:
            return None
        return {
            "url": f"data:{self._files[path]};base64,{base64.b64encode(raw).decode('ascii')}",
            "name": Path(path).name,
            "kind": "image",
            "mime": self._files[path],
        }

    def close(self) -> None:
        self._closed = True
        self._files.clear()
        self._bytes = 0
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None
