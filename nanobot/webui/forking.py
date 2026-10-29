"""WebUI chat fork orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from loguru import logger

from nanobot.session.display_history import HistoryReader
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


async def replace_webui_chat_input(
    channel: WebUIForkHost, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Confirm a versioned source and replace both histories before execution."""
    from dataclasses import asdict

    from nanobot.bus.events import InboundMessage
    from nanobot.runtime_context import public_history_message
    from nanobot.session.history_edit import (
        HistoryEditError,
        HistoryEditSource,
        HistoryEditTarget,
        ordinary_text_error,
    )
    from nanobot.session.history_visibility import is_hidden_history_message
    from nanobot.session.manager import history_prefix_boundary
    from nanobot.session.webui_turns import (
        clear_websocket_turn_if_current,
        register_queued_websocket_turn_if_idle,
    )
    from nanobot.webui.history import fact_from_record
    from nanobot.webui.metadata import WEBSOCKET_TURN_OWNER_METADATA_KEY
    from nanobot.webui.transcript import (
        build_user_transcript_event,
        build_webui_thread_response,
        prompt_index_revision,
        transcript_edit_target,
    )

    gateway = channel.gateway
    chat_id, text, turn_id, raw_source = (
        payload.get("chat_id"), payload.get("text"), payload.get("turn_id"), payload.get("source"),
    )
    if (payload.get("mode") != "replace" or not is_valid_webui_chat_id(chat_id)
            or not isinstance(text, str) or not text.strip()
            or not isinstance(turn_id, str) or not turn_id or len(turn_id) > 128
            or not isinstance(raw_source, dict)):
        raise HistoryEditError("edit_invalid_request")
    fields = cast(dict[str, Any], raw_source)
    revision, message_id, source_turn_id, original_text = (
        fields.get("revision"), fields.get("message_id"), fields.get("turn_id"), fields.get("text"),
    )
    if (not isinstance(revision, str) or not revision or not isinstance(message_id, str)
            or not isinstance(original_text, str)
            or (source_turn_id is not None and not isinstance(source_turn_id, str))):
        raise HistoryEditError("edit_invalid_request")
    source = HistoryEditSource(revision, message_id, source_turn_id)
    if gateway.unified_session:
        raise HistoryEditError("edit_shared_history")
    if gateway.ingress.validate_text(text) is not None:
        raise HistoryEditError("edit_text_too_large")
    assert gateway.session_manager is not None
    assert gateway.replace_user_input is not None
    key = webui_session_key(chat_id)
    manager = gateway.session_manager
    current = await manager.state.read(key)
    if current is None:
        raise HistoryEditError("edit_source_changed")
    raw_receipt = current.metadata.get("history_edit_receipt")
    receipt = cast(dict[str, Any], raw_receipt) if isinstance(raw_receipt, dict) else None
    if receipt is not None and receipt.get("turn_id") == turn_id:
        if (receipt.get("text"), receipt.get("source")) != (text, asdict(source)):
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

    def projection(session: Session, history: HistoryReader) -> HistoryEditTarget:
        if prompt_index_revision(key, (session.generation, session.revision), history=history) != source.revision:
            raise HistoryEditError("edit_source_changed")
        target = transcript_edit_target(key, source.message_id, source.turn_id, history=history)
        if target is None or target[0].get("text") != original_text:
            raise HistoryEditError("edit_source_changed")
        row, user_index, ordinal, position = target
        if reason := ordinary_text_error({**row, "role": "user", "content": original_text}):
            raise HistoryEditError(reason)
        if row.get("turn_id"):
            users = [item for item in session.messages if item.get("role") == "user" and not is_hidden_history_message(item)]
            matches = [index for index, item in enumerate(users) if item.get("webui_turn_id") == row["turn_id"]]
            if len(matches) != 1:
                raise HistoryEditError("edit_source_changed")
            user_index = matches[0]
        boundary = history_prefix_boundary(session, user_index)
        if boundary is None or boundary == len(session.messages):
            raise HistoryEditError("edit_source_changed")
        original = session.messages[boundary]
        if (public_history_message(original).get("content") != original_text
                or original.get("webui_turn_id") != row.get("turn_id")):
            raise HistoryEditError("edit_source_changed")
        if reason := ordinary_text_error(original):
            raise HistoryEditError(reason)
        retired_turn_ids.extend(list(dict.fromkeys(
            fact.turn_id for turn, offset, fact in history.navigation()
            if (turn, offset) >= (ordinal, position) and fact.turn_id is not None
        ))[-256:])
        event = build_user_transcript_event(chat_id, text)
        assert event is not None
        gateway.transcripts.prepare_event(chat_id, event, metadata=message.metadata, phase="user")
        event["created_at_ms"] = int(message.timestamp.timestamp() * 1000)
        return HistoryEditTarget(boundary, ordinal, position, fact_from_record(event))

    async def accepted(session: Session) -> None:
        nonlocal committed
        committed = True
        body = await manager.state.project_history(key, lambda history: build_webui_thread_response(
            key, history=history,
            session_messages_loader=lambda: session.messages,
            session_version_loader=lambda: manager.read_session_version(key),
        ))
        assert body is not None
        body["history_generation"] = session.generation
        body["active_turn_id"] = turn_id
        body["has_pending_tool_calls"] = True
        await channel.announce_webui_history_replacement(
            chat_id, body, retired_turn_ids=retired_turn_ids, previous_generation=current.generation,
        )

    try:
        await gateway.replace_user_input(message, source, projection, accepted)
    except BaseException:
        if not committed:
            clear_websocket_turn_if_current(chat_id, queued_owner)
        raise
    return {"accepted": True, "turn_id": turn_id}
