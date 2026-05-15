"""Legacy WebUI JSON snapshot path helpers (JSON file); transcripts use webui_transcript."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.session.manager import SessionManager
from nanobot.utils.webui_transcript import delete_webui_transcript


def webui_thread_file_path(session_key: str) -> Path:
    stem = SessionManager.safe_key(session_key)
    return get_webui_dir() / f"{stem}.json"


def delete_webui_thread(session_key: str) -> bool:
    """Remove legacy WebUI JSON snapshot and append-only transcript for *session_key*."""
    removed = False
    path = webui_thread_file_path(session_key)
    if path.is_file():
        try:
            path.unlink()
            removed = True
        except OSError as e:
            logger.warning("Failed to delete webui thread file {}: {}", path, e)
    if delete_webui_transcript(session_key):
        removed = True
    return removed
