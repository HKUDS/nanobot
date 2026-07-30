"""Cache-only WebUI session list index."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import (
    _SESSION_LIST_PREVIEW_MAX_CHARS,  # pyright: ignore[reportPrivateUsage]
    _SESSION_LIST_PREVIEW_MAX_RECORDS,  # pyright: ignore[reportPrivateUsage]
    SessionInfo,
    SessionManager,
    _message_preview_text,  # pyright: ignore[reportPrivateUsage]
)

_INDEX_VERSION = 5
_INDEX_FILENAME = ".webui_session_index.json"
_MODEL_PRESET_FIELD = "model_preset"
_STORED_UPDATED_AT = "stored_updated_at"
_STORED_PREVIEW = "stored_preview"
_WEBUI_ACTIVITY_MTIME_NS = "webui_activity_mtime_ns"
_WEBUI_ACTIVITY_SIZE = "webui_activity_size"
_VISIBLE_TRANSCRIPT_ROLES = {"user", "assistant"}


def list_webui_sessions(session_manager: SessionManager) -> list[dict[str, Any]]:
    index_dir = session_manager.workspace / "sessions"
    rows, changed = _reconcile_index(session_manager)
    if changed:
        try:
            _write_index_rows(index_dir, rows)
        except Exception as e:
            logger.debug("Failed to write WebUI session list index: {}", e)
    return sorted((_public_row(row) for row in rows), key=lambda row: row["updated_at"], reverse=True)


def _reconcile_index(session_manager: SessionManager) -> tuple[list[dict[str, Any]], bool]:
    existing_rows = _read_index_rows(session_manager.workspace / "sessions")
    existing_by_key = {
        row.get("key"): row
        for row in existing_rows or []
        if isinstance(row.get("key"), str)
    }
    rows: list[dict[str, Any]] = []
    changed = existing_rows is None

    for stored in session_manager.list_sessions():
        key = stored["key"]
        activity_signature = _webui_activity_signature(key)
        row = existing_by_key.get(key)
        if row is not None and _indexed_row_matches(
            row,
            stored,
            activity_signature,
        ):
            rows.append(row)
            continue

        changed = True
        payload = session_manager.read_session_file(key)
        if payload is None:
            continue
        raw_messages: object = payload.get("messages", [])
        messages = (
            [
                cast(dict[str, Any], message)
                for message in cast(list[object], raw_messages)
                if isinstance(message, dict)
            ]
            if isinstance(raw_messages, list)
            else []
        )
        rows.append(
            _indexed_row(
                stored,
                messages,
                activity_signature,
            )
        )

    if existing_rows is not None and rows != existing_rows:
        changed = True
    return rows, changed


def _index_path(sessions_dir: Path) -> Path:
    return sessions_dir / _INDEX_FILENAME


def _read_index_rows(sessions_dir: Path) -> list[dict[str, Any]] | None:
    path = _index_path(sessions_dir)
    if not path.is_file():
        return None
    try:
        raw_data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw_data, dict):
        return None
    data = cast(dict[str, Any], raw_data)
    if data.get("version") != _INDEX_VERSION:
        return None
    raw_rows: object = data.get("sessions")
    if not isinstance(raw_rows, list):
        return None
    rows = cast(list[object], raw_rows)
    if not all(isinstance(row, dict) for row in rows):
        return None
    return [cast(dict[str, Any], row) for row in rows]


def _write_index_rows(sessions_dir: Path, rows: list[dict[str, Any]]) -> None:
    path = _index_path(sessions_dir)
    tmp_path = path.with_suffix(".json.tmp")
    data = {"version": _INDEX_VERSION, "sessions": rows}
    try:
        tmp_path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _indexed_row_matches(
    row: dict[str, Any],
    stored: SessionInfo,
    activity_signature: dict[str, int],
) -> bool:
    text_fields = (
        "key",
        "created_at",
        "updated_at",
        "title",
        "preview",
        "path",
        _STORED_UPDATED_AT,
        _STORED_PREVIEW,
    )
    if not all(isinstance(row.get(field), str) for field in text_fields):
        return False
    return (
        row.get("key") == stored["key"]
        and row.get("created_at") == stored["created_at"]
        and row.get(_STORED_UPDATED_AT) == stored["updated_at"]
        and row.get("title") == stored["title"]
        and row.get(_STORED_PREVIEW) == stored["preview"]
        and row.get("path") == stored["path"]
        and row.get(_MODEL_PRESET_FIELD) == stored["model_preset"]
        and row.get(_WEBUI_ACTIVITY_MTIME_NS)
        == activity_signature[_WEBUI_ACTIVITY_MTIME_NS]
        and row.get(_WEBUI_ACTIVITY_SIZE) == activity_signature[_WEBUI_ACTIVITY_SIZE]
    )


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row.get("key"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "title": row.get("title", ""),
        "preview": row.get("preview", ""),
        _MODEL_PRESET_FIELD: row.get(_MODEL_PRESET_FIELD),
        "path": row.get("path", ""),
    }


def _preview_from_messages(messages: list[dict[str, Any]]) -> str:
    fallback_preview = ""
    scanned_records = 0
    scanned_chars = 0
    for item in messages:
        scanned_records += 1
        scanned_chars += len(json.dumps(item, ensure_ascii=False)) + 1
        if (
            scanned_records > _SESSION_LIST_PREVIEW_MAX_RECORDS
            or scanned_chars > _SESSION_LIST_PREVIEW_MAX_CHARS
        ):
            break
        if is_hidden_history_message(item):
            continue
        text = _message_preview_text(item)
        if not text:
            continue
        if item.get("role") == "user":
            return text
        if not fallback_preview and item.get("role") == "assistant":
            fallback_preview = text
    return fallback_preview


def _webui_activity_paths(session_key: str) -> list[Path]:
    stem = SessionManager.safe_key(session_key)
    webui_dir = get_webui_dir()
    return [webui_dir / f"{stem}.jsonl", webui_dir / f"{stem}.json"]


def _webui_activity_signature(session_key: str) -> dict[str, int]:
    latest_mtime_ns = 0
    total_size = 0
    for path in _webui_activity_paths(session_key):
        try:
            stat = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
        total_size += stat.st_size
    return {
        _WEBUI_ACTIVITY_MTIME_NS: latest_mtime_ns,
        _WEBUI_ACTIVITY_SIZE: total_size,
    }


def _webui_activity_updated_at(signature: dict[str, int]) -> str | None:
    mtime_ns = signature.get(_WEBUI_ACTIVITY_MTIME_NS, 0)
    if mtime_ns <= 0:
        return None
    return datetime.fromtimestamp(mtime_ns / 1_000_000_000).isoformat()


def _timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


def _latest_updated_at(stored: str | None, activity: str | None) -> str | None:
    if _timestamp(activity) > _timestamp(stored):
        return activity
    return stored


def _visible_message_timestamp(item: dict[str, Any]) -> str | None:
    if is_hidden_history_message(item) or item.get("role") not in _VISIBLE_TRANSCRIPT_ROLES:
        return None
    timestamp = item.get("timestamp")
    return timestamp if isinstance(timestamp, str) else None


def _last_visible_message_at(messages: list[dict[str, Any]]) -> str | None:
    latest: str | None = None
    for item in messages:
        latest = _latest_updated_at(latest, _visible_message_timestamp(item))
    return latest


def _visible_activity_updated_at(
    stored: str | None,
    visible_message_at: str | None,
    webui_activity: str | None,
) -> str | None:
    return _latest_updated_at(visible_message_at, webui_activity) or stored


def _indexed_row(
    stored: SessionInfo,
    messages: list[dict[str, Any]],
    activity_signature: dict[str, int],
) -> dict[str, Any]:
    return {
        "key": stored["key"],
        "created_at": stored["created_at"],
        "updated_at": _visible_activity_updated_at(
            stored["updated_at"],
            _last_visible_message_at(messages),
            _webui_activity_updated_at(activity_signature),
        ),
        "title": stored["title"],
        "preview": _preview_from_messages(messages),
        _MODEL_PRESET_FIELD: stored["model_preset"],
        "path": stored["path"],
        _STORED_UPDATED_AT: stored["updated_at"],
        _STORED_PREVIEW: stored["preview"],
        **activity_signature,
    }
