"""On-disk JSON persistence for WebUI display threads (separate from agent session)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.session.manager import SessionManager

WEBUI_THREAD_SCHEMA_VERSION = 1
# Guardrail: large transcripts / base64 remnants should not blow RAM on parse.
_MAX_THREAD_FILE_BYTES = 8 * 1024 * 1024


def webui_thread_file_path(session_key: str) -> Path:
    stem = SessionManager.safe_key(session_key)
    return get_webui_dir() / f"{stem}.json"


def read_webui_thread(session_key: str) -> dict[str, Any] | None:
    path = webui_thread_file_path(session_key)
    if not path.is_file():
        return None
    size = path.stat().st_size
    if size > _MAX_THREAD_FILE_BYTES:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_webui_thread_atomic(session_key: str, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > _MAX_THREAD_FILE_BYTES:
        msg = "webui thread payload too large"
        raise ValueError(msg)
    path = webui_thread_file_path(session_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def delete_webui_thread(session_key: str) -> bool:
    """Remove the on-disk WebUI thread snapshot for *session_key*, if present.

    Best-effort: mirrors :meth:`SessionManager.delete_session` cleanup so list
    deletion does not leave orphaned ``webui/*.json`` files.
    """
    path = webui_thread_file_path(session_key)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError as e:
        logger.warning("Failed to delete webui thread file {}: {}", path, e)
        return False
