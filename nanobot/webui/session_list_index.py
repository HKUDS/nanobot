"""Cache-only WebUI session list index.

The core ``SessionManager`` owns model context while the WebUI transcript owns
durable display history. The sidebar discovers both without reconstructing one
store from the other, so core session writes stay independent from UI state.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.config.paths import get_webui_dir
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import (
    _PROVIDER_STATE_RECORD_TYPE,  # pyright: ignore[reportPrivateUsage]
    _SESSION_LIST_PREVIEW_MAX_CHARS,  # pyright: ignore[reportPrivateUsage]
    _SESSION_LIST_PREVIEW_MAX_RECORDS,  # pyright: ignore[reportPrivateUsage]
    Session,
    SessionManager,
    _is_provider_state_record_line,  # pyright: ignore[reportPrivateUsage]
    _message_preview_text,  # pyright: ignore[reportPrivateUsage]
    _metadata_title,  # pyright: ignore[reportPrivateUsage]
)
from nanobot.session.model_selection import model_preset_from_metadata
from nanobot.session.recovery import recovery_state_from_metadata
from nanobot.webui.session_identity import (
    WEBUI_SESSION_STORAGE_PREFIX,
    is_webui_session_key,
    webui_chat_id,
    webui_session_key,
)

_INDEX_VERSION = 8
_INDEX_FILENAME = ".webui_session_index.json"
_MODEL_PRESET_FIELD = "model_preset"
_ROW_SOURCE_FIELD = "_source"
_SESSION_SOURCE = "session"
_TRANSCRIPT_SOURCE = "webui_transcript"
_WORKSPACE_SCOPE_PRESENT_FIELD = "_workspace_scope_present"
_WORKSPACE_SCOPE_VALUE_FIELD = "_workspace_scope_value"
WEBUI_SESSION_INDEX_INTERNAL_FIELDS = frozenset(
    {_WORKSPACE_SCOPE_PRESENT_FIELD, _WORKSPACE_SCOPE_VALUE_FIELD}
)
_INDEXED_WORKSPACE_SCOPE_KEYS = ("project_path", "path", "access_mode")
_MAX_INDEXED_WORKSPACE_SCOPE_BYTES = 4096
_WEBUI_ACTIVITY_MTIME_NS = "webui_activity_mtime_ns"
_WEBUI_ACTIVITY_SIZE = "webui_activity_size"
_WEBUI_ACTIVITY_FILES = "webui_activity_files"
_VISIBLE_TRANSCRIPT_ROLES = {"user", "assistant"}
_WEBUI_SESSION_STEM_PREFIX = SessionManager.safe_key(WEBUI_SESSION_STORAGE_PREFIX)
_WEBUI_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")
_TRANSCRIPT_SEGMENTS_SUFFIX = ".segments"
_TRANSCRIPT_NON_ANSWER_KINDS = {"progress", "reasoning", "tool_hint"}


def list_webui_sessions(session_manager: SessionManager) -> list[dict[str, Any]]:
    """Return session rows for the WebUI sidebar, backed by a rebuildable cache."""
    with session_manager.locked_session_files():
        rows, changed = _reconcile_index(session_manager)
        if changed:
            try:
                _write_index_rows(session_manager.sessions_dir, rows)
            except Exception as e:
                logger.debug("Failed to write WebUI session list index: {}", e)
    sessions = [
        _public_row(session_manager.sessions_dir, get_webui_dir(), row)
        for row in rows
    ]
    return sorted(sessions, key=lambda row: row.get("updated_at", ""), reverse=True)


def _reconcile_index(session_manager: SessionManager) -> tuple[list[dict[str, Any]], bool]:
    existing_rows = _read_index_rows(session_manager.sessions_dir)
    existing_by_source = {
        (row.get(_ROW_SOURCE_FIELD), row.get("file")): row
        for row in existing_rows or []
        if isinstance(row.get(_ROW_SOURCE_FIELD), str)
        and isinstance(row.get("file"), str)
    }
    webui_dir = get_webui_dir()
    session_paths: dict[str, Path] = {}
    for path in sorted(session_manager.sessions_dir.glob("*.jsonl")):
        key = SessionManager._session_key_from_path(path)  # pyright: ignore[reportPrivateUsage]
        if key is not None:
            session_paths[key] = path

    session_keys_by_stem = {
        SessionManager.safe_key(key): key
        for key in session_paths
        if is_webui_session_key(key)
    }
    rows: list[dict[str, Any]] = []
    changed = existing_rows is None
    expected_sources: set[tuple[str, str]] = set()

    for key, path in sorted(session_paths.items()):
        identity = (_SESSION_SOURCE, path.name)
        row = existing_by_source.get(identity)
        if row is not None and _indexed_row_matches_file(row, path, webui_dir):
            rows.append(row)
            expected_sources.add(identity)
            continue

        changed = True
        scanned = _scan_session_row(session_manager, path, webui_dir)
        if scanned is not None:
            rows.append(scanned)
            expected_sources.add(identity)

    for stem, paths in _webui_transcript_sources(webui_dir).items():
        if stem in session_keys_by_stem:
            continue
        identity = (_TRANSCRIPT_SOURCE, stem)
        row = existing_by_source.get(identity)
        cached_key = row.get("key") if row is not None else None
        key = (
            cached_key
            if isinstance(cached_key, str) and _valid_transcript_session_key(cached_key, stem)
            else None
        )
        if key is not None and row is not None and _indexed_transcript_row_matches(
            row,
            key,
            webui_dir,
        ):
            rows.append(row)
            expected_sources.add(identity)
            continue

        changed = True
        scanned = _scan_transcript_row(key, stem, paths, webui_dir)
        scanned_key = scanned.get("key") if scanned is not None else None
        if scanned is not None and scanned_key not in session_paths:
            rows.append(scanned)
            expected_sources.add(identity)

    if set(existing_by_source) != expected_sources:
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
    if not isinstance(data, dict):
        return None
    index_data = cast(dict[str, Any], data)
    if index_data.get("version") != _INDEX_VERSION:
        return None
    rows = index_data.get("sessions")
    if not isinstance(rows, list):
        return None
    index_rows = cast(list[Any], rows)
    if not all(isinstance(row, dict) for row in index_rows):
        return None
    return [cast(dict[str, Any], row) for row in index_rows]


def _write_index_rows(sessions_dir: Path, rows: list[dict[str, Any]]) -> None:
    path = _index_path(sessions_dir)
    tmp_path = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    data = {"version": _INDEX_VERSION, "sessions": rows}
    try:
        with open(tmp_path, "x", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False) + "\n")
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _file_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def _indexed_row_matches_file(row: dict[str, Any], path: Path, webui_dir: Path) -> bool:
    if not all(isinstance(row.get(key), str) for key in ("key", "created_at", "updated_at")):
        return False
    if not isinstance(row.get("title", ""), str) or not isinstance(row.get("preview", ""), str):
        return False
    if not isinstance(row.get(_WORKSPACE_SCOPE_PRESENT_FIELD), bool):
        return False
    if row.get(_ROW_SOURCE_FIELD) != _SESSION_SOURCE or row.get("file") != path.name:
        return False
    try:
        signature = _file_signature(path)
    except OSError:
        return False
    activity_signature = _webui_activity_signature(str(row.get("key")), webui_dir)
    return (
        row.get("mtime_ns") == signature["mtime_ns"]
        and row.get("size") == signature["size"]
        and row.get(_WEBUI_ACTIVITY_MTIME_NS) == activity_signature[_WEBUI_ACTIVITY_MTIME_NS]
        and row.get(_WEBUI_ACTIVITY_SIZE) == activity_signature[_WEBUI_ACTIVITY_SIZE]
        and row.get(_WEBUI_ACTIVITY_FILES) == activity_signature[_WEBUI_ACTIVITY_FILES]
    )


def _indexed_transcript_row_matches(
    row: dict[str, Any],
    session_key: str,
    webui_dir: Path,
) -> bool:
    if not all(isinstance(row.get(key), str) for key in ("key", "created_at", "updated_at")):
        return False
    if row.get(_ROW_SOURCE_FIELD) != _TRANSCRIPT_SOURCE:
        return False
    if row.get("key") != session_key or row.get("file") != SessionManager.safe_key(session_key):
        return False
    if not isinstance(row.get("title", ""), str) or not isinstance(row.get("preview", ""), str):
        return False
    if not isinstance(row.get(_WORKSPACE_SCOPE_PRESENT_FIELD), bool):
        return False
    signature = _webui_activity_signature(session_key, webui_dir)
    return (
        row.get(_WEBUI_ACTIVITY_MTIME_NS) == signature[_WEBUI_ACTIVITY_MTIME_NS]
        and row.get(_WEBUI_ACTIVITY_SIZE) == signature[_WEBUI_ACTIVITY_SIZE]
        and row.get(_WEBUI_ACTIVITY_FILES) == signature[_WEBUI_ACTIVITY_FILES]
    )


def _public_row(sessions_dir: Path, webui_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    file = str(row.get("file", ""))
    if row.get(_ROW_SOURCE_FIELD) == _TRANSCRIPT_SOURCE:
        path = webui_dir / f"{file}.jsonl"
    else:
        path = sessions_dir / file
    return {
        "key": row.get("key"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "title": row.get("title", ""),
        "preview": row.get("preview", ""),
        _MODEL_PRESET_FIELD: row.get(_MODEL_PRESET_FIELD),
        "recovery_state": row.get("recovery_state"),
        _WORKSPACE_SCOPE_PRESENT_FIELD: row.get(_WORKSPACE_SCOPE_PRESENT_FIELD, False),
        _WORKSPACE_SCOPE_VALUE_FIELD: row.get(_WORKSPACE_SCOPE_VALUE_FIELD),
        "path": str(path),
    }


def indexed_workspace_scope(row: dict[str, Any]) -> tuple[bool, object]:
    """Return the cached sidebar scope value while preserving missing vs null."""
    return (
        row.get(_WORKSPACE_SCOPE_PRESENT_FIELD) is True,
        cast(object, row.get(_WORKSPACE_SCOPE_VALUE_FIELD)),
    )


def _indexed_workspace_scope_fields(metadata: object) -> dict[str, object]:
    if not isinstance(metadata, dict):
        return {
            _WORKSPACE_SCOPE_PRESENT_FIELD: False,
            _WORKSPACE_SCOPE_VALUE_FIELD: None,
        }
    metadata_data = cast(dict[str, Any], metadata)
    if WORKSPACE_SCOPE_METADATA_KEY not in metadata_data:
        return {
            _WORKSPACE_SCOPE_PRESENT_FIELD: False,
            _WORKSPACE_SCOPE_VALUE_FIELD: None,
        }

    raw_scope = metadata_data.get(WORKSPACE_SCOPE_METADATA_KEY)
    indexed_scope: object = False
    if raw_scope is None:
        indexed_scope = None
    elif isinstance(raw_scope, dict):
        scope_data = cast(dict[object, object], raw_scope)
        recognized = {
            key: scope_data[key]
            for key in _INDEXED_WORKSPACE_SCOPE_KEYS
            if key in scope_data
        }
        try:
            encoded = json.dumps(recognized, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
        else:
            if len(encoded.encode("utf-8")) <= _MAX_INDEXED_WORKSPACE_SCOPE_BYTES:
                indexed_scope = cast(object, json.loads(encoded))
    return {
        _WORKSPACE_SCOPE_PRESENT_FIELD: True,
        _WORKSPACE_SCOPE_VALUE_FIELD: indexed_scope,
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


def _webui_transcript_record_paths(stem: str, webui_dir: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    segments_dir = webui_dir / f"{stem}{_TRANSCRIPT_SEGMENTS_SUFFIX}"
    if segments_dir.is_dir() and not segments_dir.is_symlink():
        try:
            paths.extend(
                sorted(
                    path
                    for path in segments_dir.glob("*.jsonl")
                    if path.is_file() and not path.is_symlink()
                )
            )
        except OSError:
            pass
    active = webui_dir / f"{stem}.jsonl"
    if active.is_file() and not active.is_symlink():
        paths.append(active)
    return tuple(paths)


def _webui_transcript_sources(webui_dir: Path) -> dict[str, tuple[Path, ...]]:
    stems: set[str] = set()
    try:
        entries = tuple(webui_dir.iterdir())
    except OSError:
        return {}
    for path in entries:
        if path.is_symlink():
            continue
        if path.is_file() and path.suffix == ".jsonl":
            stem = path.stem
        elif path.is_dir() and path.name.endswith(_TRANSCRIPT_SEGMENTS_SUFFIX):
            stem = path.name.removesuffix(_TRANSCRIPT_SEGMENTS_SUFFIX)
        else:
            continue
        if stem.startswith(_WEBUI_SESSION_STEM_PREFIX):
            stems.add(stem)
    return {
        stem: paths
        for stem in sorted(stems)
        if (paths := _webui_transcript_record_paths(stem, webui_dir))
    }


def _transcript_record(line: str) -> dict[str, Any] | None:
    try:
        value: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _valid_transcript_session_key(key: str, stem: str) -> bool:
    chat_id = webui_chat_id(key)
    if chat_id is None:
        return False
    return _WEBUI_CHAT_ID_RE.fullmatch(chat_id) is not None and SessionManager.safe_key(key) == stem


def _webui_activity_paths(session_key: str, webui_dir: Path) -> list[Path]:
    stem = SessionManager.safe_key(session_key)
    paths = [
        webui_dir / f"{stem}.jsonl",
        webui_dir / f"{stem}.json",
    ]
    segments_dir = webui_dir / f"{stem}{_TRANSCRIPT_SEGMENTS_SUFFIX}"
    if segments_dir.is_dir() and not segments_dir.is_symlink():
        try:
            paths.extend(
                sorted(
                    path
                    for path in segments_dir.iterdir()
                    if path.is_file() and not path.is_symlink()
                )
            )
        except OSError:
            pass
    return paths


def _webui_activity_signature(session_key: str, webui_dir: Path) -> dict[str, int]:
    latest_mtime_ns = 0
    total_size = 0
    file_count = 0
    for path in _webui_activity_paths(session_key, webui_dir):
        try:
            stat = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        file_count += 1
        latest_mtime_ns = max(latest_mtime_ns, stat.st_mtime_ns)
        total_size += stat.st_size
    return {
        _WEBUI_ACTIVITY_MTIME_NS: latest_mtime_ns,
        _WEBUI_ACTIVITY_SIZE: total_size,
        _WEBUI_ACTIVITY_FILES: file_count,
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
    if item.get("role") not in _VISIBLE_TRANSCRIPT_ROLES:
        return None
    if is_hidden_history_message(item):
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


def _indexed_row_for_session(session: Session, path: Path, webui_dir: Path) -> dict[str, Any]:
    signature = _file_signature(path)
    activity_signature = _webui_activity_signature(session.key, webui_dir)
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
        _MODEL_PRESET_FIELD: model_preset_from_metadata(session.metadata),
        "recovery_state": recovery_state_from_metadata(session.metadata),
        **_indexed_workspace_scope_fields(session.metadata),
        _ROW_SOURCE_FIELD: _SESSION_SOURCE,
        "file": path.name,
        "mtime_ns": signature["mtime_ns"],
        "size": signature["size"],
        **activity_signature,
    }


def _transcript_preview(record: dict[str, Any]) -> tuple[str, str]:
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        return "", ""
    preview = _message_preview_text({"content": text})
    if not preview:
        return "", ""
    event = record.get("event")
    if event == "user" or record.get("role") == "user":
        return preview, ""
    if (
        event == "message"
        and record.get("kind") not in _TRANSCRIPT_NON_ANSWER_KINDS
    ) or record.get("role") == "assistant":
        return "", preview
    return "", ""


def _transcript_created_at(record: dict[str, Any]) -> str | None:
    value = record.get("created_at_ms")
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or value < 0
    ):
        return None
    try:
        return datetime.fromtimestamp(value / 1000).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _scan_transcript_row(
    session_key: str | None,
    stem: str,
    paths: tuple[Path, ...],
    webui_dir: Path,
) -> dict[str, Any] | None:
    path_key = session_key or webui_session_key(
        stem.removeprefix(_WEBUI_SESSION_STEM_PREFIX)
    )
    signature = _webui_activity_signature(path_key, webui_dir)
    activity_updated_at = _webui_activity_updated_at(signature)
    if activity_updated_at is None:
        return None

    preview = ""
    fallback_preview = ""
    created_at: str | None = None
    saw_record = False
    scanned_records = 0
    scanned_chars = 0
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    scanned_records += 1
                    scanned_chars += len(line)
                    record = _transcript_record(line)
                    if record is not None:
                        saw_record = True
                        chat_id = record.get("chat_id")
                        if isinstance(chat_id, str) and chat_id.strip():
                            candidate = webui_session_key(chat_id.strip())
                            if _valid_transcript_session_key(candidate, stem):
                                session_key = candidate
                        if created_at is None:
                            created_at = _transcript_created_at(record)
                        user_preview, assistant_preview = _transcript_preview(record)
                        if user_preview:
                            preview = user_preview
                            break
                        if not fallback_preview and assistant_preview:
                            fallback_preview = assistant_preview
                    if (
                        scanned_records >= _SESSION_LIST_PREVIEW_MAX_RECORDS
                        or scanned_chars >= _SESSION_LIST_PREVIEW_MAX_CHARS
                    ):
                        break
        except OSError:
            continue
        if preview or (
            scanned_records >= _SESSION_LIST_PREVIEW_MAX_RECORDS
            or scanned_chars >= _SESSION_LIST_PREVIEW_MAX_CHARS
        ):
            break
    if not saw_record:
        return None
    if session_key is None:
        fallback = webui_session_key(stem.removeprefix(_WEBUI_SESSION_STEM_PREFIX))
        if not _valid_transcript_session_key(fallback, stem):
            return None
        session_key = fallback

    if created_at is None:
        try:
            earliest_mtime = min(path.stat().st_mtime for path in paths)
            created_at = datetime.fromtimestamp(earliest_mtime).isoformat()
        except (OSError, OverflowError, ValueError):
            created_at = activity_updated_at
    return {
        "key": session_key,
        "created_at": created_at,
        "updated_at": activity_updated_at,
        "title": "",
        "preview": preview or fallback_preview,
        _MODEL_PRESET_FIELD: None,
        "recovery_state": None,
        **_indexed_workspace_scope_fields({}),
        _ROW_SOURCE_FIELD: _TRANSCRIPT_SOURCE,
        "file": stem,
        "mtime_ns": signature[_WEBUI_ACTIVITY_MTIME_NS],
        "size": signature[_WEBUI_ACTIVITY_SIZE],
        **signature,
    }


def _scan_session_row(
    session_manager: SessionManager,
    path: Path,
    webui_dir: Path,
) -> dict[str, Any] | None:
    storage_key = SessionManager._session_key_from_path(path)  # pyright: ignore[reportPrivateUsage]
    if storage_key is None:
        return None
    try:
        signature = _file_signature(path)
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
                if _is_provider_state_record_line(line):
                    continue
                item = json.loads(line)
                if item.get("_type") == _PROVIDER_STATE_RECORD_TYPE:
                    continue
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
            created_at_s = data.get("created_at")
            updated_at_s = data.get("updated_at")
            if not created_at_s or not updated_at_s:
                fallback_time = datetime.fromtimestamp(signature["mtime_ns"] / 1e9).isoformat()
                created_at_s = created_at_s or fallback_time
                updated_at_s = updated_at_s or fallback_time
            key = data.get("key") or storage_key
            metadata = data.get("metadata", {})
            activity_signature = _webui_activity_signature(key, webui_dir)
            activity_updated_at = _webui_activity_updated_at(activity_signature)
            return {
                "key": key,
                "created_at": created_at_s,
                "updated_at": _visible_activity_updated_at(
                    updated_at_s,
                    visible_message_at,
                    activity_updated_at,
                ),
                "title": _metadata_title(metadata),
                "preview": preview or fallback_preview,
                _MODEL_PRESET_FIELD: model_preset_from_metadata(metadata),
                "recovery_state": recovery_state_from_metadata(metadata),
                **_indexed_workspace_scope_fields(metadata),
                _ROW_SOURCE_FIELD: _SESSION_SOURCE,
                "file": path.name,
                "mtime_ns": signature["mtime_ns"],
                "size": signature["size"],
                **activity_signature,
            }
    except Exception:
        repaired = session_manager._repair(storage_key)  # pyright: ignore[reportPrivateUsage]
        if repaired is None:
            return None
        return _indexed_row_for_session(repaired, path, webui_dir)
