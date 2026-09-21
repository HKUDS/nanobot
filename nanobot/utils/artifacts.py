"""Artifact persistence helpers for generated media."""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from nanobot.config.paths import get_media_dir
from nanobot.utils.helpers import detect_image_mime, ensure_dir
from nanobot.utils.image_artifacts import (
    MAX_IMAGE_BYTES,
    EphemeralImageStore,
    ImageArtifact,
    ImageArtifactResult,
)

_DATA_IMAGE_RE = re.compile(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.*)$", re.DOTALL)
_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

class ArtifactError(ValueError):
    """Raised when an artifact cannot be safely decoded or stored."""


def decode_image_data_url(data_url: str) -> tuple[bytes, str]:
    """Decode a base64 image data URL and return ``(bytes, mime)``."""
    if len(data_url) > ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 128:
        raise ArtifactError("image exceeds the 32 MiB artifact limit")
    match = _DATA_IMAGE_RE.match(data_url.strip())
    if match is None:
        raise ArtifactError("expected a base64 image data URL")

    declared_mime, encoded = match.groups()
    try:
        raw = base64.b64decode(encoded, validate=True)
    except binascii.Error as exc:
        raise ArtifactError("invalid base64 image payload") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise ArtifactError("image exceeds the 32 MiB artifact limit")

    detected_mime = detect_image_mime(raw)
    if detected_mime is None:
        raise ArtifactError("unsupported or unrecognized image data")
    if declared_mime != detected_mime:
        declared_mime = detected_mime
    return raw, declared_mime


def _safe_relative_dir(save_dir: str) -> Path:
    normalized = save_dir.replace("\\", "/").strip("/")
    if not normalized:
        raise ArtifactError("save_dir must not be empty")
    rel = PurePosixPath(normalized)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ArtifactError("save_dir must be a safe relative path")
    return Path(*rel.parts)


def _artifact_root(save_dir: str) -> Path:
    media_root = get_media_dir().resolve()
    root = (media_root / _safe_relative_dir(save_dir)).resolve()
    try:
        root.relative_to(media_root)
    except ValueError as exc:
        raise ArtifactError("artifact directory escapes media root") from exc
    return root


def store_generated_image_artifact(
    data_url: str,
    *,
    prompt: str,
    model: str,
    source_images: list[str] | None = None,
    save_dir: str = "generated",
    provider: str = "openrouter",
    created_at: datetime | None = None,
    ephemeral_store: EphemeralImageStore | None = None,
) -> dict[str, Any]:
    """Persist a generated image and sidecar metadata under the media root."""
    raw, mime = decode_image_data_url(data_url)
    ext = _MIME_EXTENSIONS.get(mime)
    if ext is None:
        raise ArtifactError(f"unsupported image MIME type: {mime}")

    now = created_at or datetime.now().astimezone()
    artifact_id = f"img_{uuid.uuid4().hex[:12]}"
    if ephemeral_store is not None:
        try:
            image_path = ephemeral_store.store(artifact_id, raw, mime, ext)
        except ValueError as exc:
            raise ArtifactError(str(exc)) from exc
        return {"id": artifact_id, "path": str(image_path), "mime": mime,
                "provider": provider, "created_at": now.isoformat()}
    day_dir = ensure_dir(_artifact_root(save_dir) / now.strftime("%Y-%m-%d"))
    image_path = day_dir / f"{artifact_id}{ext}"
    metadata_path = day_dir / f"{artifact_id}.json"

    image_path.write_bytes(raw)
    metadata: dict[str, Any] = {
        "id": artifact_id,
        "path": str(image_path),
        "mime": mime,
        "prompt": prompt,
        "model": model,
        "provider": provider,
        "source_images": list(source_images or []),
        "created_at": now.isoformat(),
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metadata


def generated_image_tool_result(
    artifacts: list[dict[str, Any]], *, automatic_delivery: bool = False,
) -> str:
    """Return the compact structured result exposed to the LLM."""
    delivery = (
        "WebUI displays up to 32 unique images per turn automatically; do not send them again. "
        if automatic_delivery else
        "Call the message tool with the artifact paths in the media parameter "
        "to deliver the images to the user. "
    )
    content = json.dumps(
        {
            "artifacts": artifacts,
            "next_step": (
                "Use these artifact paths as reference_images for follow-up edits. "
                + delivery + "Keep raw paths internal unless the "
                "user asks for debug details."
            ),
        },
        ensure_ascii=False,
    )
    return ImageArtifactResult(content, tuple(
        ImageArtifact(str(a["id"]), str(a["path"]), str(a["mime"]), str(a["provider"]))
        for a in artifacts
    ))
