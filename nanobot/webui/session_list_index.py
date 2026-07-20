"""Cache-only WebUI session list index.

The core ``SessionManager`` owns durable conversation history. This module owns
the WebUI sidebar optimization so core session writes stay independent from UI
presentation caches.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import (
    _SESSION_LIST_PREVIEW_MAX_CHARS,
    _SESSION_LIST_PREVIEW_MAX_RECORDS,
    Session,
    SessionManager,
    _message_preview_text,
    _metadata_title,
)

_INDEX_VERSION = 3
_INDEX_FILENAME = ".webui_session_index.json"
_WEBUI_ACTIVITY_MTIME_NS = "webui_activity_mtime_ns"
_WEBUI_ACTIVITY_SIZE = "webui_activity_size"
_WEBUI_ACTIVITY_REVISION = "webui_activity_revision"
_VISIBLE_TRANSCRIPT_ROLES = {"user", "assistant"}

IndexedActivity = Mapping[str, Mapping[str, int]]


def list_webui_sessions(
    session_manager: SessionManager,
    *,
    indexed_activity: IndexedActivity | None = None,
) -> list[dict[str, Any]]:
    """Return session rows for the WebUI sidebar, backed by a rebuildable cache."""
    rows, changed = _reconcile_index(session_manager, indexed_activity=indexed_activity)
    if changed:
        try:
            _write_index_rows(session_manager.sessions_dir, rows)
        except Exception as e:
            logger.debug("Failed to write WebUI session list index: {}", e)
    sessions = [_public_row(session_manager.sessions_dir, row) for row in rows]
    return sorted(sessions, key=lambda row: row.get("updated_at", ""), reverse=True)


def _reconcile_index(
    session_manager: SessionManager,
    *,
    indexed_activity: IndexedActivity | None,
) -> tuple[list[dict[str, Any]], bool]:
    existing_rows = _read_index_rows(session_manager.sessions_dir)
    existing_by_file = {
        row.get("file"): row
        for row in existing_rows or []
        if isinstance(row.get("file"), str)
    }
    paths = sorted(session_manager.sessions_dir.glob("*.jsonl"))
    rows: list[dict[str, Any]] = []
    changed = existing_rows is None

    for path in paths:
        row = existing_by_file.get(path.name)
        row_matches = False
        if row is not None:
            if indexed_activity is None:
                row_matches = _indexed_row_matches_file(row, path)
            else:
                row_matches = _indexed_row_matches_file(
                    row,
                    path,
                    indexed_activity=indexed_activity,
                )
        if row_matches:
            rows.append(row)
            continue

        changed = True
        if indexed_activity is None:
            scanned = _scan_session_row(session_manager, path)
        else:
            scanned = _scan_session_row(
                session_manager,
                path,
                indexed_activity=indexed_activity,
            )
        if scanned is not None:
            rows.append(scanned)

    if set(existing_by_file) != {path.name for path in paths}:
        changed = True
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
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != _INDEX_VERSION:
        return None
    rows = data.get("sessions")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return None
    return rows


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


def _file_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def _indexed_row_matches_file(
    row: dict[str, Any],
    path: Path,
    *,
    indexed_activity: IndexedActivity | None = None,
) -> bool:
    if not all(isinstance(row.get(key), str) for key in ("key", "created_at", "updated_at")):
        return False
    if not isinstance(row.get("title", ""), str) or not isinstance(row.get("preview", ""), str):
        return False
    if row.get("file") != path.name:
        return False
    try:
        signature = _file_signature(path)
    except OSError:
        return False
    activity_signature = _webui_activity_signature(
        str(row.get("key")),
        indexed_activity=indexed_activity,
    )
    return (
        row.get("mtime_ns") == signature["mtime_ns"]
        and row.get("size") == signature["size"]
        and row.get(_WEBUI_ACTIVITY_MTIME_NS) == activity_signature[_WEBUI_ACTIVITY_MTIME_NS]
        and row.get(_WEBUI_ACTIVITY_SIZE) == activity_signature[_WEBUI_ACTIVITY_SIZE]
        and row.get(_WEBUI_ACTIVITY_REVISION) == activity_signature[_WEBUI_ACTIVITY_REVISION]
    )


def _public_row(sessions_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row.get("key"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "title": row.get("title", ""),
        "preview": row.get("preview", ""),
        "path": str(sessions_dir / str(row.get("file", ""))),
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
    return [
        webui_dir / f"{stem}.jsonl",
        webui_dir / f"{stem}.json",
    ]


def _webui_activity_signature(
    session_key: str,
    *,
    indexed_activity: IndexedActivity | None = None,
) -> dict[str, int]:
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
    indexed = (indexed_activity or {}).get(session_key, {})
    indexed_updated_at_ns = indexed.get("updated_at_ns", 0)
    indexed_revision = indexed.get("revision", 0)
    if isinstance(indexed_updated_at_ns, int):
        latest_mtime_ns = max(latest_mtime_ns, indexed_updated_at_ns)
    return {
        _WEBUI_ACTIVITY_MTIME_NS: latest_mtime_ns,
        _WEBUI_ACTIVITY_SIZE: total_size,
        _WEBUI_ACTIVITY_REVISION: indexed_revision if isinstance(indexed_revision, int) else 0,
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
    if is_hidden_history_message(item):
        return None
    if item.get("role") not in _VISIBLE_TRANSCRIPT_ROLES:
        return None
    timestamp = item.get("timestamp")
    return timestamp if isinstance(timestamp, str) else None


def _last_visible_message_at(messages: list[dict[str, Any]]) -> str | None:
    latest: str | None = None
    for item in messages:
        timestamp = _visible_message_timestamp(item)
        if timestamp is not None:
            latest = _latest_updated_at(latest, timestamp)
    return latest


def _visible_activity_updated_at(
    stored: str | None,
    visible_message_at: str | None,
    webui_activity: str | None,
) -> str | None:
    return _latest_updated_at(visible_message_at, webui_activity) or stored


def _indexed_row_for_session(
    session: Session,
    path: Path,
    *,
    indexed_activity: IndexedActivity | None = None,
) -> dict[str, Any]:
    signature = _file_signature(path)
    activity_signature = _webui_activity_signature(
        session.key,
        indexed_activity=indexed_activity,
    )
    activity_updated_at = _webui_activity_updated_at(activity_signature)
    visible_message_at = _last_visible_message_at(session.messages)
    return {
        "key": session.key,
        "created_at": session.created_at.isoformat(),
        "updated_at": _visible_activity_updated_at(
            session.updated_at.isoformat(),
            visible_message_at,
            activity_updated_at,
        ),
        "title": _metadata_title(session.metadata),
        "preview": _preview_from_messages(session.messages),
        "file": path.name,
        "mtime_ns": signature["mtime_ns"],
        "size": signature["size"],
        **activity_signature,
    }


def _scan_session_row(
    session_manager: SessionManager,
    path: Path,
    *,
    indexed_activity: IndexedActivity | None = None,
) -> dict[str, Any] | None:
    storage_key = SessionManager._decode_storage_key(path.stem)
    fallback_key = storage_key or path.stem.replace("_", ":", 1)
    try:
        with open(path, encoding="utf-8") as f:
            first_line = f.readline().strip()
            if not first_line:
                return None
            data = json.loads(first_line)
            if data.get("_type") != "metadata":
                return None
            preview = ""
            fallback_preview = ""
            visible_message_at = None
            preview_done = False
            scanned_records = 0
            scanned_chars = 0
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                timestamp = _visible_message_timestamp(item)
                if timestamp is not None:
                    visible_message_at = _latest_updated_at(visible_message_at, timestamp)
                if not preview_done:
                    scanned_records += 1
                    scanned_chars += len(line)
                    if (
                        scanned_records > _SESSION_LIST_PREVIEW_MAX_RECORDS
                        or scanned_chars > _SESSION_LIST_PREVIEW_MAX_CHARS
                    ):
                        preview_done = True
                        continue
                    if item.get("_type") == "metadata":
                        continue
                    if is_hidden_history_message(item):
                        continue
                    text = _message_preview_text(item)
                    if not text:
                        continue
                    if item.get("role") == "user":
                        preview = text
                        preview_done = True
                        continue
                    if not fallback_preview and item.get("role") == "assistant":
                        fallback_preview = text
            signature = _file_signature(path)
            created_at_s = data.get("created_at")
            updated_at_s = data.get("updated_at")
            if not created_at_s or not updated_at_s:
                fallback_time = datetime.fromtimestamp(signature["mtime_ns"] / 1e9).isoformat()
                created_at_s = created_at_s or fallback_time
                updated_at_s = updated_at_s or fallback_time
            key = data.get("key") or fallback_key
            activity_signature = _webui_activity_signature(
                key,
                indexed_activity=indexed_activity,
            )
            activity_updated_at = _webui_activity_updated_at(activity_signature)
            return {
                "key": key,
                "created_at": created_at_s,
                "updated_at": _visible_activity_updated_at(
                    updated_at_s,
                    visible_message_at,
                    activity_updated_at,
                ),
                "title": _metadata_title(data.get("metadata", {})),
                "preview": preview or fallback_preview,
                "file": path.name,
                "mtime_ns": signature["mtime_ns"],
                "size": signature["size"],
                **activity_signature,
            }
    except Exception:
        repaired = session_manager._repair(fallback_key)
        if repaired is None:
            return None
        return _indexed_row_for_session(
            repaired,
            path,
            indexed_activity=indexed_activity,
        )
