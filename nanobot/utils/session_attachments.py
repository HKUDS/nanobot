"""Session replay: ensure assistant ``media`` paths are under the media root.

WebUI history signing (``/api/.../messages``) only works for files inside
``get_media_dir``. Tool-driven attachments may live in the workspace; stage
copies into the websocket media bucket before persisting message JSON.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_media_dir
from nanobot.utils.helpers import safe_filename


def stage_media_paths_for_session_replay(paths: list[str]) -> list[str]:
    """Keep local files only; copy anything outside the media root into ``media/websocket``."""
    root = get_media_dir().resolve()
    out: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            continue
        if raw.startswith(("http://", "https://")):
            continue
        try:
            p = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if not p.is_file():
            continue
        try:
            p.relative_to(root)
            key = str(p)
        except ValueError:
            try:
                media_dir = get_media_dir("websocket")
                staged = media_dir / f"{uuid.uuid4().hex[:12]}-{safe_filename(p.name) or 'attachment'}"
                shutil.copyfile(p, staged)
                key = str(staged.resolve())
            except OSError as exc:
                logger.warning("failed to stage session media from {}: {}", raw, exc)
                continue
        if key not in seen:
            out.append(key)
            seen.add(key)
    return out


def merge_turn_media_into_last_assistant(
    all_messages: list[dict[str, Any]],
    generated_image_paths: list[str],
    extra_attachment_paths: list[str],
) -> None:
    """Attach staged paths to the last assistant row in *all_messages* (in-place)."""
    merged = list(
        dict.fromkeys(
            [
                *stage_media_paths_for_session_replay(generated_image_paths),
                *stage_media_paths_for_session_replay(extra_attachment_paths),
            ]
        )
    )
    last = all_messages[-1] if all_messages else None
    if not merged or not last or last.get("role") != "assistant":
        return
    existing = last.get("media")
    base = existing if isinstance(existing, list) else []
    last["media"] = list(dict.fromkeys([*base, *merged]))
