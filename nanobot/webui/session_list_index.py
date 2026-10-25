"""Sidebar projection from session headers and SQLite display summaries."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import model_preset_from_metadata
from nanobot.session.recovery import recovery_state_from_metadata

_WORKSPACE_SCOPE_PRESENT_FIELD = "_workspace_scope_present"
_WORKSPACE_SCOPE_VALUE_FIELD = "_workspace_scope_value"
WEBUI_SESSION_INDEX_INTERNAL_FIELDS = frozenset(
    {_WORKSPACE_SCOPE_PRESENT_FIELD, _WORKSPACE_SCOPE_VALUE_FIELD}
)
_INDEXED_WORKSPACE_SCOPE_KEYS = ("project_path", "path", "access_mode")
_MAX_INDEXED_WORKSPACE_SCOPE_BYTES = 4096


def list_webui_sessions(
    session_manager: SessionManager,
    stored_sessions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Read one database snapshot; no display files or sidebar sidecar cache."""
    stored = session_manager.list_session_metadata() if stored_sessions is None else stored_sessions
    rows: list[dict[str, Any]] = []
    for row in stored:
        metadata = row["metadata"]
        if not session_manager.types.public_history(metadata):
            continue
        millis = row["history_updated_at_ms"]
        activity = datetime.fromtimestamp(millis / 1000).isoformat() if millis else None
        rows.append({
            "key": row["key"], "created_at": row["created_at"],
            "updated_at": _visible_activity_updated_at(row["updated_at"], row["visible_updated_at"], activity),
            "title": row["title"], "preview": row["preview"] or row["history_preview"],
            "model_preset": model_preset_from_metadata(metadata),
            "recovery_state": recovery_state_from_metadata(metadata),
            **_indexed_workspace_scope_fields(metadata), "path": row["path"],
        })
    return sorted(rows, key=lambda row: row.get("updated_at", ""), reverse=True)


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


def _visible_activity_updated_at(
    stored: str | None,
    visible_message_at: str | None,
    webui_activity: str | None,
) -> str | None:
    return _latest_updated_at(visible_message_at, webui_activity) or stored
