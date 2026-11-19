"""Durable user image blocks and their model-facing replay projection."""

from __future__ import annotations

import re
from collections.abc import Sequence
from hashlib import sha256
from typing import Any, TypedDict, cast

from nanobot.config.paths import get_data_dir
from nanobot.providers.images import REPLAYED_IMAGE_META
from nanobot.utils.atomic_file import atomic_write_text, io_path, read_atomic_bytes

_IMAGE_REF = "image_attachment"
_IMAGE_ID = re.compile(r"[0-9a-f]{64}")
IMAGE_UNAVAILABLE = "[Previous image unavailable]"


class ImageAttachment(TypedDict):
    type: str
    id: str


def persist_user_image_blocks(content: Sequence[object]) -> list[object]:
    """Replace inline images with attachment references for session replay."""
    stored: list[object] = []
    for value in content:
        block = cast(dict[str, object], value) if isinstance(value, dict) else {}
        image = block.get("image_url")
        url = cast(dict[str, object], image).get("url") if isinstance(image, dict) else None
        if block.get("type") != "image_url" or not isinstance(url, str) or not url.startswith("data:image/"):
            stored.append(cast(object, value))
            continue
        image_id = sha256(url.encode("ascii")).hexdigest()
        directory = io_path(get_data_dir() / "session-images")
        path = directory / image_id
        if not path.is_file():
            directory.mkdir(mode=0o700, exist_ok=True)
            atomic_write_text(path, url)
        ref: ImageAttachment = {"type": _IMAGE_REF, "id": image_id}
        stored.append(ref)
    return stored


def replay_user_image_blocks(content: Any, *, load_images: bool) -> Any:
    if not isinstance(content, list):
        return content
    replay: list[object] = []
    for value in cast(list[object], content):
        block = cast(dict[str, object], value) if isinstance(value, dict) else {}
        if block.get("type") == _IMAGE_REF:
            url = _load_image(block.get("id")) if load_images else None
            if url is not None:
                replay.append({
                    "type": "image_url", "image_url": {"url": url},
                    "_meta": {REPLAYED_IMAGE_META: True},
                })
            else:
                replay.append({"type": "text", "text": IMAGE_UNAVAILABLE if load_images else "[image]"})
        elif block.get("type") == "image_url":
            # Temporary sessions keep their images in memory only.
            replay.append(
                {**block, "_meta": {REPLAYED_IMAGE_META: True}}
                if load_images else {"type": "text", "text": "[image]"}
            )
        else:
            replay.append(cast(object, value))
    return replay


def user_message_text(content: object) -> str:
    """Read visible text without expanding image attachments."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for value in cast(list[object], content):
        if isinstance(value, dict):
            block = cast(dict[str, object], value)
            if block.get("type") == "text" and isinstance(text := block.get("text"), str):
                parts.append(text)
    return "\n".join(parts)


def _load_image(image_id: object) -> str | None:
    if not isinstance(image_id, str) or not _IMAGE_ID.fullmatch(image_id):
        return None
    try:
        path = io_path(get_data_dir() / "session-images" / image_id)
        if not path.is_file():
            return None
        data = read_atomic_bytes(path)
        if data.startswith(b"data:image/") and sha256(data).hexdigest() == image_id:
            return data.decode("ascii")
    except (OSError, UnicodeError):
        pass
    return None
