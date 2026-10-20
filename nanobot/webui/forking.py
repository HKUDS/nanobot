"""WebUI chat fork orchestration."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from nanobot.session.manager import Session, SessionManager
from nanobot.session.webui_turns import clean_generated_title
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key
from nanobot.webui.transcript import session_display_facts

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

    from nanobot.webui.gateway_services import GatewayServices


class WebUIForkHost(Protocol):
    gateway: GatewayServices

    async def send_webui_protocol_error(
        self,
        connection: ServerConnection,
        detail: str,
    ) -> None: ...

    async def announce_webui_history_replacement(
        self, chat_id: str, body: dict[str, Any], *, retired_turn_ids: list[str], previous_generation: str,
    ) -> None: ...

    async def attach_webui_fork(
        self,
        connection: ServerConnection,
        *,
        fork_id: str,
        fork_key: str,
    ) -> None: ...


async def create_webui_chat_fork(
    session_manager: SessionManager,
    *,
    source_chat_id: str,
    before_user_index: int,
    title: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(chat_id, session_key)`` for a new fork, or ``None`` for bad input."""
    new_id = str(uuid.uuid4())
    source_key = webui_session_key(source_chat_id)
    target_key = webui_session_key(new_id)
    forked = await session_manager.state.fork(
        source_key, target_key, before_user_index,
        title=clean_generated_title(title), history_projection=session_display_facts,
    )
    if forked is None:
        return None
    return new_id, target_key


async def handle_webui_fork_chat(
    channel: WebUIForkHost,
    connection: ServerConnection,
    envelope: Mapping[str, Any],
) -> None:
    """Handle the WebUI ``fork_chat`` websocket command.

    ``websocket.py`` owns the transport. This module owns WebUI fork semantics:
    validate the request, clone session/transcript state, attach the new chat,
    and hydrate the client.
    """
    if envelope.get("mode", "new") != "new":
        await channel.send_webui_protocol_error(connection, "replace requires an acknowledged WebUI request")
        return
    source_chat_id = envelope.get("source_chat_id")
    raw_index = envelope.get("before_user_index")
    if not is_valid_webui_chat_id(source_chat_id):
        await channel.send_webui_protocol_error(connection, "invalid source_chat_id")
        return
    if isinstance(raw_index, bool) or not isinstance(raw_index, int) or raw_index < 0:
        await channel.send_webui_protocol_error(connection, "invalid before_user_index")
        return

    session_manager = channel.gateway.session_manager
    if session_manager is None:
        await channel.send_webui_protocol_error(connection, "session_manager_unavailable")
        return

    try:
        forked = await create_webui_chat_fork(
            session_manager,
            source_chat_id=source_chat_id,
            before_user_index=raw_index,
            title=envelope.get("title") if isinstance(envelope.get("title"), str) else None,
        )
        if forked is None:
            await channel.send_webui_protocol_error(connection, "invalid fork source or index")
            return
        fork_id, fork_key = forked
    except Exception as exc:
        logger.warning("fork_chat failed: {}", exc)
        await channel.send_webui_protocol_error(connection, "fork_chat_failed")
        return

    await channel.attach_webui_fork(
        connection,
        fork_id=fork_id,
        fork_key=fork_key,
    )


async def prepare_webui_chat_edit(
    gateway: GatewayServices, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Issue a source-version anchor after checking display/canonical identity."""
    from dataclasses import asdict

    from nanobot.runtime_context import public_history_message
    from nanobot.session.history_edit import (
        HistoryEditAnchor,
        HistoryEditError,
        message_digest,
        ordinary_text_error,
    )
    from nanobot.session.history_visibility import is_hidden_history_message
    from nanobot.session.manager import history_prefix_boundary
    from nanobot.session.webui_turns import websocket_turn_wall_started_at
    from nanobot.webui.history_replacement import transcript_access
    from nanobot.webui.transcript import transcript_edit_target, webui_transcript_revision

    chat_id, user_index = payload.get("chat_id"), payload.get("user_index")
    message_id, text, turn_id = payload.get("message_id"), payload.get("text"), payload.get("turn_id")
    if (not is_valid_webui_chat_id(chat_id) or isinstance(user_index, bool)
            or not isinstance(user_index, int) or user_index < 0
            or not isinstance(message_id, str) or not isinstance(text, str)
            or (turn_id is not None and not isinstance(turn_id, str))):
        raise HistoryEditError("edit_invalid_request")
    if gateway.unified_session or gateway.session_manager is None or gateway.replace_user_input is None:
        raise HistoryEditError("edit_unavailable")
    if websocket_turn_wall_started_at(chat_id) is not None:
        raise HistoryEditError("edit_session_busy")
    key = webui_session_key(chat_id)
    source = await gateway.session_manager.state.read(key)
    if source is None:
        raise HistoryEditError("edit_source_changed")
    if any(source.metadata.get(name) for name in ("pending_user_turn", "pending_user_followups", "runtime_checkpoint")):
        raise HistoryEditError("edit_session_busy")

    def check_display() -> tuple[dict[str, Any], int, str]:
        with transcript_access(key):
            target = transcript_edit_target(key, message_id, turn_id)
            if target is None or target[0].get("text") != text:
                raise HistoryEditError("edit_source_changed")
            row, display_index = target
            if row.get("session_message") or row.get("source"):
                raise HistoryEditError("edit_special_message")
            if reason := ordinary_text_error({**row, "role": "user", "content": text}):
                raise HistoryEditError(reason)
            revision = webui_transcript_revision(key)
            if revision is None:
                raise HistoryEditError("edit_source_changed")
            return row, display_index, revision

    row, display_index, display_revision = await asyncio.to_thread(check_display)
    persisted_turn_id = row.get("turn_id")
    if persisted_turn_id:
        users = [item for item in source.messages if item.get("role") == "user" and not is_hidden_history_message(item)]
        matches = [index for index, item in enumerate(users) if item.get("webui_turn_id") == persisted_turn_id]
        if len(matches) != 1:
            raise HistoryEditError("edit_source_changed")
        user_index = matches[0]
    else:
        user_index = display_index
    boundary = history_prefix_boundary(source, user_index)
    if boundary is None or boundary == len(source.messages):
        raise HistoryEditError("edit_source_changed")
    message = source.messages[boundary]
    if public_history_message(message).get("content") != text:
        raise HistoryEditError("edit_source_changed")
    if reason := ordinary_text_error(message):
        raise HistoryEditError(reason)
    return {
        "anchor": {**asdict(HistoryEditAnchor(
            source.generation, source.revision, user_index, message_digest(message),
        )), "transcript_revision": display_revision, "transcript_user_index": display_index,
                   "display_message_id": message_id, "display_turn_id": turn_id},
        "text": text,
    }


async def replace_webui_chat_input(
    channel: WebUIForkHost, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """The replace branch of fork_chat: accept and execute in the same session."""
    from contextlib import contextmanager
    from typing import Iterator

    from nanobot.bus.events import InboundMessage
    from nanobot.session.history_edit import HistoryEditAnchor, HistoryEditError
    from nanobot.session.webui_turns import (
        clear_websocket_turn_if_current,
        register_queued_websocket_turn_if_idle,
    )
    from nanobot.webui.history_replacement import replace_transcript, transcript_access
    from nanobot.webui.metadata import WEBSOCKET_TURN_OWNER_METADATA_KEY
    from nanobot.webui.transcript import (
        build_user_transcript_event,
        build_webui_thread_response,
        read_transcript_lines,
        transcript_edit_target,
        transcript_prefix_before_user_index,
        webui_transcript_revision,
    )

    gateway = channel.gateway
    chat_id, text, turn_id, raw_anchor = (
        payload.get("chat_id"), payload.get("text"), payload.get("turn_id"), payload.get("anchor"),
    )
    if (payload.get("mode") != "replace" or not is_valid_webui_chat_id(chat_id)
            or not isinstance(text, str) or not text.strip()
            or not isinstance(turn_id, str) or not turn_id or len(turn_id) > 128
            or not isinstance(raw_anchor, dict)):
        raise HistoryEditError("edit_invalid_request")
    if gateway.unified_session or gateway.session_manager is None or gateway.replace_user_input is None:
        raise HistoryEditError("edit_unavailable")
    if gateway.ingress.validate_text(text) is not None:
        raise HistoryEditError("edit_text_too_large")
    try:
        anchor = HistoryEditAnchor(**{name: raw_anchor[name] for name in (
            "generation", "revision", "user_index", "message_digest",
        )})
    except (KeyError, TypeError):
        raise HistoryEditError("edit_invalid_request") from None
    if (not isinstance(anchor.generation, str) or not isinstance(anchor.message_digest, str)
            or isinstance(anchor.revision, bool) or not isinstance(anchor.revision, int)
            or isinstance(anchor.user_index, bool) or not isinstance(anchor.user_index, int)
            or isinstance(raw_anchor.get("transcript_user_index"), bool)
            or not isinstance(raw_anchor.get("transcript_user_index"), int)):
        raise HistoryEditError("edit_invalid_request")
    key = webui_session_key(chat_id)
    manager = gateway.session_manager
    source = await manager.state.read(key)
    receipt = source.metadata.get("history_edit_receipt") if source is not None else None
    if isinstance(receipt, dict) and receipt.get("turn_id") == turn_id:
        if (receipt.get("text"), receipt.get("source_generation"), receipt.get("source_revision")) != (
            text, anchor.generation, anchor.revision,
        ):
            raise HistoryEditError("edit_request_conflict")
        return {"accepted": True, "turn_id": turn_id}
    queued_owner = register_queued_websocket_turn_if_idle(chat_id, turn_id)
    if queued_owner is None:
        raise HistoryEditError("edit_session_busy")
    message = InboundMessage(
        channel="websocket", chat_id=chat_id, sender_id="webui", content=text,
        metadata={"webui": True, "_wants_stream": True, "webui_turn_id": turn_id,
                  "_webui_history_replacement": True,
                  WEBSOCKET_TURN_OWNER_METADATA_KEY: queued_owner},
    )
    retired_turn_ids: list[str] = []
    committed = False

    @contextmanager
    def projection(session: Session) -> Iterator[None]:
        with transcript_access(key):
            if webui_transcript_revision(key) != raw_anchor.get("transcript_revision"):
                raise HistoryEditError("edit_source_changed")
            target = transcript_edit_target(key, raw_anchor.get("display_message_id", ""), raw_anchor.get("display_turn_id"))
            if target is None or target[1] != raw_anchor["transcript_user_index"] or source is None:
                raise HistoryEditError("edit_source_changed")
            from nanobot.runtime_context import public_history_message
            from nanobot.session.manager import history_prefix_boundary
            boundary = history_prefix_boundary(source, anchor.user_index)
            if boundary is None or boundary == len(source.messages):
                raise HistoryEditError("edit_source_changed")
            original = source.messages[boundary]
            if (target[0].get("text") != public_history_message(original).get("content")
                    or target[0].get("turn_id") != original.get("webui_turn_id")):
                raise HistoryEditError("edit_source_changed")
            lines = read_transcript_lines(key)
            prefix = transcript_prefix_before_user_index(lines, raw_anchor["transcript_user_index"])
            if prefix is None:
                raise HistoryEditError("edit_source_changed")
            retired_turn_ids.extend(list(dict.fromkeys(
                row["turn_id"] for row in lines if isinstance(row.get("turn_id"), str)
            ))[-256:])
            event = build_user_transcript_event(chat_id, text)
            assert event is not None
            gateway.transcripts.prepare_event(chat_id, event, metadata=message.metadata, phase="user")
            event["created_at_ms"] = int(message.timestamp.timestamp() * 1000)
            with replace_transcript(
                key, [*prefix, event], database=manager.sessions_dir / "sessions.sqlite3",
                generation=session.generation,
            ):
                yield

    async def accepted(session: Session) -> None:
        nonlocal committed
        committed = True
        body = await asyncio.to_thread(build_webui_thread_response, key)
        assert body is not None
        body["history_generation"] = session.generation
        body["active_turn_id"] = turn_id
        body["has_pending_tool_calls"] = True
        await channel.announce_webui_history_replacement(
            chat_id, body, retired_turn_ids=retired_turn_ids, previous_generation=anchor.generation,
        )

    try:
        await gateway.replace_user_input(message, anchor, projection, accepted)
    except BaseException:
        if not committed:
            clear_websocket_turn_if_current(chat_id, queued_owner)
        raise
    return {"accepted": True, "turn_id": turn_id}
