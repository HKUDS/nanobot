"""Helpers for WebUI chat forking.

The WebSocket channel owns transport concerns only. This module owns the
WebUI-specific session/transcript work needed to make a fork look like a normal
chat in both browser WebUI and desktop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from blackcat.session.manager import SessionManager
from blackcat.session.webui_turns import WEBUI_TITLE_METADATA_KEY, clean_generated_title
from blackcat.webui.transcript import (
    append_fork_marker,
    delete_webui_transcript,
    fork_transcript_before_user_index,
    write_session_messages_as_transcript,
)


@dataclass(frozen=True)
class WebuiForkResult:
    chat_id: str
    session_key: str


def create_webui_chat_fork(
    session_manager: SessionManager,
    *,
    source_chat_id: str,
    before_user_index: int,
    title: str | None = None,
) -> WebuiForkResult | None:
    """Create a WebUI chat fork from a completed assistant-turn boundary.

    Returns ``None`` when the source/index is invalid. Exceptions are reserved
    for unexpected I/O or persistence failures and are rolled back before being
    re-raised.
    """
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
    return WebuiForkResult(chat_id=new_id, session_key=target_key)
