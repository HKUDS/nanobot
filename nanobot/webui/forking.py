"""WebUI chat fork orchestration."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Mapping
from typing import Any

from loguru import logger

from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WEBUI_TITLE_METADATA_KEY, clean_generated_title
from nanobot.webui.transcript import (
    WebUITranscriptRecorder,
    append_fork_marker,
    delete_webui_transcript,
    fork_transcript_before_user_index,
    write_session_messages_as_transcript,
)

_WEBUI_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")


def _valid_webui_chat_id(value: Any) -> bool:
    return isinstance(value, str) and _WEBUI_CHAT_ID_RE.match(value) is not None


def create_webui_chat_fork(
    session_manager: SessionManager,
    *,
    source_chat_id: str,
    before_user_index: int,
    title: str | None = None,
    transcripts: WebUITranscriptRecorder | None = None,
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

        if transcripts is None:
            transcript_ok = fork_transcript_before_user_index(
                source_key,
                target_key,
                before_user_index,
            )
            if not transcript_ok:
                write_session_messages_as_transcript(target_key, forked.messages)
            append_fork_marker(target_key)
        else:
            transcript_ok = transcripts.fork_before_user_index(
                source_key,
                target_key,
                before_user_index,
            )
            if not transcript_ok:
                transcripts.write_session_messages(target_key, forked.messages)
            transcripts.append_fork_marker(target_key)

        fork_title = clean_generated_title(title)
        if fork_title:
            forked.metadata[WEBUI_TITLE_METADATA_KEY] = fork_title
            session_manager.save(forked, fsync=True)
    except Exception:
        try:
            if transcripts is None:
                delete_webui_transcript(target_key)
            else:
                transcripts.delete(target_key)
        except Exception as cleanup_error:
            logger.warning(
                "Failed to clean up WebUI transcript for fork {}: {}",
                target_key,
                cleanup_error,
            )
        try:
            session_manager.delete_session(target_key)
        except Exception as cleanup_error:
            logger.warning(
                "Failed to clean up fork session {}: {}",
                target_key,
                cleanup_error,
            )
        raise
    return new_id, target_key


async def handle_webui_fork_chat(channel: Any, connection: Any, envelope: Mapping[str, Any]) -> None:
    """Handle the WebUI ``fork_chat`` websocket command.

    ``websocket.py`` owns the transport. This module owns WebUI fork semantics:
    validate the request, clone session/transcript state, attach the new chat,
    and hydrate the client.
    """
    source_chat_id = envelope.get("source_chat_id")
    raw_index = envelope.get("before_user_index")
    if not _valid_webui_chat_id(source_chat_id):
        await channel._send_event(connection, "error", detail="invalid source_chat_id")
        return
    if isinstance(raw_index, bool) or not isinstance(raw_index, int) or raw_index < 0:
        await channel._send_event(connection, "error", detail="invalid before_user_index")
        return

    session_manager = channel.gateway.session_manager
    if session_manager is None:
        await channel._send_event(connection, "error", detail="session_manager_unavailable")
        return

    try:
        forked = await asyncio.to_thread(
            create_webui_chat_fork,
            session_manager,
            source_chat_id=source_chat_id,
            before_user_index=raw_index,
            title=envelope.get("title") if isinstance(envelope.get("title"), str) else None,
            transcripts=channel._transcripts,
        )
        if forked is None:
            await channel._send_event(connection, "error", detail="invalid fork source or index")
            return
        fork_id, fork_key = forked
    except Exception as exc:
        channel.logger.warning("fork_chat failed: {}", exc)
        await channel._send_event(connection, "error", detail="fork_chat_failed")
        return

    scope = channel._workspaces.scope_for_session_key(fork_key)
    channel._attach(connection, fork_id)
    await channel._send_event(connection, "attached", chat_id=fork_id)
    await channel._send_event(
        connection,
        "session_updated",
        chat_id=fork_id,
        scope="metadata",
        workspace_scope=scope.payload(),
    )
    await channel._hydrate_after_subscribe(fork_id)
