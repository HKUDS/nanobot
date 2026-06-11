"""Cache-only WebUI session list index.

The core ``SessionManager`` owns durable conversation history. This module owns
the WebUI sidebar optimization so core session writes stay independent from UI
presentation caches.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from blackcat.session.manager import (
    _SESSION_LIST_PREVIEW_MAX_CHARS,
    _SESSION_LIST_PREVIEW_MAX_RECORDS,
    Session,
    SessionManager,
    _message_preview_text,
    _metadata_title,
)

_INDEX_VERSION = 1
_INDEX_FILENAME = ".webui_session_index.json"


def list_webui_sessions(session_manager: SessionManager) -> list[dict[str, Any]]:
    """Return session rows for the WebUI sidebar, backed by a rebuildable cache."""
    rows, changed = _reconcile_index(session_manager)
    if changed:
        try:
            _write_index_rows(session_manager.sessions_dir, rows)
        except Exception as e:
            logger.debug("Failed to write WebUI session list index: {}", e)
    sessions = [_public_row(session_manager.sessions_dir, row) for row in rows]
    return sorted(sessions, key=lambda row: row.get("updated_at", ""), reverse=True)


def _reconcile_index(session_manager: SessionManager) -> tuple[list[dict[str, Any]], bool]:
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
        if row is not None and _indexed_row_matches_file(row, path):
            rows.append(row)
            continue

        changed = True
        scanned = _scan_session_row(session_manager, path)
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


def _indexed_row_matches_file(row: dict[str, Any], path: Path) -> bool:
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
    return row.get("mtime_ns") == signature["mtime_ns"] and row.get("size") == signature["size"]


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
        text = _message_preview_text(item)
        if not text:
            continue
        if item.get("role") == "user":
            return text
        if not fallback_preview and item.get("role") == "assistant":
            fallback_preview = text
    return fallback_preview


def _indexed_row_for_session(session: Session, path: Path) -> dict[str, Any]:
    signature = _file_signature(path)
    return {
        "key": session.key,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "title": _metadata_title(session.metadata),
        "preview": _preview_from_messages(session.messages),
        "file": path.name,
        "mtime_ns": signature["mtime_ns"],
        "size": signature["size"],
    }


def _scan_session_row(session_manager: SessionManager, path: Path) -> dict[str, Any] | None:
    fallback_key = path.stem.replace("_", ":", 1)
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
            scanned_records = 0
            scanned_chars = 0
            for line in f:
                if not line.strip():
                    continue
                scanned_records += 1
                scanned_chars += len(line)
                if (
                    scanned_records > _SESSION_LIST_PREVIEW_MAX_RECORDS
                    or scanned_chars > _SESSION_LIST_PREVIEW_MAX_CHARS
                ):
                    break
                item = json.loads(line)
                if item.get("_type") == "metadata":
                    continue
                text = _message_preview_text(item)
                if not text:
                    continue
                if item.get("role") == "user":
                    preview = text
                    break
                if not fallback_preview and item.get("role") == "assistant":
                    fallback_preview = text
            signature = _file_signature(path)
            return {
                "key": data.get("key") or fallback_key,
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "title": _metadata_title(data.get("metadata", {})),
                "preview": preview or fallback_preview,
                "file": path.name,
                "mtime_ns": signature["mtime_ns"],
                "size": signature["size"],
            }
    except Exception:
        repaired = session_manager._repair(fallback_key)
        if repaired is None:
            return None
        return _indexed_row_for_session(repaired, path)
