"""WebUI chat fork orchestration."""

from __future__ import annotations

import uuid

from blackcat.session.manager import SessionManager
from blackcat.session.webui_turns import WEBUI_TITLE_METADATA_KEY, clean_generated_title
from blackcat.webui.transcript import (
    append_fork_marker,
    delete_webui_transcript,
    fork_transcript_before_user_index,
    write_session_messages_as_transcript,
)


def create_webui_chat_fork(
    session_manager: SessionManager,
    *,
    source_chat_id: str,
    before_user_index: int,
    title: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(chat_id, session_key)`` for a new fork, or ``None`` for bad input."""
    new_id = str(uuid.uuid4())
    source_key = f"websocket:{source_chat_id}"
    target_key = f"websocket:{new_id}"
    try:
        forked = session_manager.fork_session_before_user_index(
            source_key,
            target_key,
            before_user_index,
        )
        if forked is None:
            return None

        transcript_ok = fork_transcript_before_user_index(
            source_key,
            target_key,
            before_user_index,
        )
        if not transcript_ok:
            write_session_messages_as_transcript(target_key, forked.messages)
        append_fork_marker(target_key)

        fork_title = clean_generated_title(title)
        if fork_title:
            forked.metadata[WEBUI_TITLE_METADATA_KEY] = fork_title
            session_manager.save(forked, fsync=True)
    except Exception:
        delete_webui_transcript(target_key)
        session_manager.delete_session(target_key)
        raise
    return new_id, target_key
