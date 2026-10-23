"""Authoritative WebUI topic titles and the temporary sidebar-title import.

0.4.x is the final import window. Remove the sidebar-title import in 0.5.0;
installs with only legacy sidebar titles must pass through 0.4.x first.
"""

from __future__ import annotations

import asyncio
from typing import Any

from nanobot.session.manager import SessionManager, metadata_title
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.webui.session_identity import is_webui_session_key
from nanobot.webui.sidebar_state import (
    consume_legacy_title_overrides,
    read_webui_sidebar_state,
)


def _valid_title(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    title = value.strip()
    return title if title and len(title) <= 160 else None


async def rename_session_title(
    sessions: SessionManager, key: str, title: str, *, expected_title: str | None,
    expected_generation: str | None = None, importing: bool = False,
) -> bool:
    """Write one existing, public session's title; never create a missing session."""
    if not is_webui_session_key(key) or _valid_title(title) != title:
        raise ValueError("invalid session title")
    record = await sessions.state.read_metadata(key)
    if record is None or not sessions.types.public_history(record["metadata"]):
        raise SessionConflictError("session not found")
    if importing and record["metadata"].get("title_user_edited") is True:
        return False
    generation = expected_generation
    if importing:
        version = await asyncio.to_thread(sessions.read_session_version, key)
        generation = version[0] if version is not None else None
    if generation is None:
        raise SessionConflictError("session generation missing")

    def change(metadata: dict[str, Any]) -> bool:
        if not sessions.types.public_history(metadata):
            raise SessionConflictError("session not found")
        if importing and metadata.get("title_user_edited") is True:
            return False
        if expected_title is not None and metadata_title(metadata) != expected_title:
            raise SessionConflictError("session title changed")
        metadata["title"] = title
        metadata["title_user_edited"] = True
        return True

    changed, _metadata = await sessions.state.mutate_metadata(
        key, change, expected_generation=generation,
    )
    return changed


async def migrate_legacy_session_titles(sessions: SessionManager) -> bool:
    """Import available titles; retry missing sessions on later requests."""
    sidebar = await asyncio.to_thread(read_webui_sidebar_state, strict=True)
    imported: dict[str, str] = {}
    for key, title in sidebar["title_overrides"].items():
        if not is_webui_session_key(key):
            continue
        try:
            await rename_session_title(sessions, key, title, expected_title=None, importing=True)
        except SessionConflictError:
            # Missing/deleted sessions must not be recreated by the importer.
            continue
        imported[key] = title
    await asyncio.to_thread(consume_legacy_title_overrides, imported)
    remaining = await asyncio.to_thread(read_webui_sidebar_state, strict=True)
    return not any(is_webui_session_key(key) for key in remaining["title_overrides"])
