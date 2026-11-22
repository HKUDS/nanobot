from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    WEBUI_QUOTE_SOURCE,
    public_history_message,
)
from nanobot.session.display_history import HistoryFact, HistoryReader
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import Session, SessionManager, history_prefix_boundary
from nanobot.session.state import ForkError
from nanobot.session.webui_turns import (
    clean_generated_title,
    clear_websocket_turn_if_current,
    register_queued_websocket_turn_if_idle,
)
from nanobot.webui.history import fact_from_record
from nanobot.webui.metadata import WEBSOCKET_TURN_OWNER_METADATA_KEY
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key
from nanobot.webui.transcript import (
    build_user_transcript_event,
    build_webui_thread_response,
    find_fork_input,
    session_display_facts,
)

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

    from nanobot.webui.gateway_services import GatewayServices


class WebUIForkHost(Protocol):
    gateway: GatewayServices

    async def send_webui_protocol_error(
        self,
        connection: ServerConnection,
        detail: str,
        *,
        request_id: str | None = None,
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
        request_id: str | None = None,
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
    *,
    request_id: str | None = None,
) -> None:
    """Handle the WebUI ``fork_chat`` websocket command.

    ``websocket.py`` owns the transport. This module owns WebUI fork semantics:
    validate the request, clone session/transcript state, attach the new chat,
    and hydrate the client.
    """
    request_fields = {"request_id": request_id} if request_id is not None else {}
    if envelope.get("mode", "new") != "new":
        await channel.send_webui_protocol_error(connection, "replace requires an acknowledged WebUI request", **request_fields)
        return
    source_chat_id = envelope.get("source_chat_id")
    raw_index = envelope.get("before_user_index")
    if not is_valid_webui_chat_id(source_chat_id):
        await channel.send_webui_protocol_error(connection, "invalid source_chat_id", **request_fields)
        return
    if isinstance(raw_index, bool) or not isinstance(raw_index, int) or raw_index < 0:
        await channel.send_webui_protocol_error(connection, "invalid before_user_index", **request_fields)
        return

    session_manager = channel.gateway.session_manager
    if session_manager is None:
        await channel.send_webui_protocol_error(connection, "session_manager_unavailable", **request_fields)
        return

    try:
        forked = await create_webui_chat_fork(
            session_manager,
            source_chat_id=source_chat_id,
            before_user_index=raw_index,
            title=envelope.get("title") if isinstance(envelope.get("title"), str) else None,
        )
        if forked is None:
            await channel.send_webui_protocol_error(connection, "invalid fork source or index", **request_fields)
            return
        fork_id, fork_key = forked
    except Exception as exc:
        logger.warning("fork_chat failed: {}", exc)
        await channel.send_webui_protocol_error(connection, "fork_chat_failed", **request_fields)
        return

    await channel.attach_webui_fork(
        connection,
        fork_id=fork_id,
        fork_key=fork_key,
        **request_fields,
    )


def _plain_fork_text(message: dict[str, Any]) -> str:
    if message.get("role") != "user" or any(message.get(key) for key in (
        "_hidden_history", "_command", "session_message", "injected_event", "source", "automation",
        "automation_id", "cron_job_id", "_automation_turn", "_user_shell",
    )):
        raise ForkError("edit_special_message")
    if any(message.get(key) for key in ("media", "media_paths", "media_urls")):
        raise ForkError("edit_attachments_unsupported")
    if any(message.get(key) for key in ("cli_apps", "mcp_presets", "session_mentions")):
        raise ForkError("edit_mentions_unsupported")
    text = public_history_message(message).get("content")
    if not isinstance(text, str) or not text.strip():
        raise ForkError("edit_plain_text_only")
    context = message.get(RUNTIME_CONTEXT_HISTORY_META)
    sources: list[str] = cast(dict[str, Any], context).get("sources", []) if isinstance(context, dict) else []
    if WEBUI_QUOTE_SOURCE in sources or text.startswith("> [!QUOTE]"):
        raise ForkError("edit_context_unsupported")
    if any(source in sources for source in ("session_mentions", "cli_apps", "mcp_presets")):
        raise ForkError("edit_mentions_unsupported")
    if "session_message" in sources:
        raise ForkError("edit_special_message")
    if text.lstrip().startswith(("/", "!")):
        raise ForkError("edit_commands_unsupported")
    if re.search(r"(^|\s)@[\w-]+", text):
        raise ForkError("edit_mentions_unsupported")
    return text


async def fork_webui_chat_in_place(
    channel: WebUIForkHost, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep the prefix before the selected input in this chat and resume from the new text."""

    gateway = channel.gateway
    chat_id, text, turn_id, source_id = (
        payload.get("chat_id"), payload.get("text"), payload.get("turn_id"), payload.get("source_id"),
    )
    if (payload.get("mode") != "replace" or not is_valid_webui_chat_id(chat_id)
            or not isinstance(text, str) or not text.strip()
            or not isinstance(turn_id, str) or not turn_id or len(turn_id) > 128
            or not isinstance(source_id, str) or not source_id):
        raise ForkError("edit_invalid_request")
    if gateway.ingress.validate_text(text) is not None:
        raise ForkError("edit_text_too_large")
    _plain_fork_text({"role": "user", "content": text})
    if gateway.session_manager is None or gateway.fork_in_place is None:
        raise ForkError("edit_unavailable")
    key = webui_session_key(chat_id)
    manager = gateway.session_manager
    queued_owner = register_queued_websocket_turn_if_idle(chat_id, turn_id)
    message = InboundMessage(
        channel="websocket", chat_id=chat_id, sender_id="webui", content=text,
        metadata={"webui": True, "_wants_stream": True, "webui_turn_id": turn_id,
                  "_webui_history_replacement": True,
                  WEBSOCKET_TURN_OWNER_METADATA_KEY: queued_owner},
    )
    if queued_owner is None:
        await manager.state.fork_in_place(key, source_id, message, None)
        return {"accepted": True, "turn_id": turn_id}
    retired_turn_ids: list[str] = []
    previous_generation = ""
    committed = False

    def locate(session: Session, history: HistoryReader) -> tuple[int, int, int, HistoryFact]:
        nonlocal previous_generation
        previous_generation = session.generation
        if history.has_input(f"user:{turn_id}") or any(m.get("webui_turn_id") == turn_id for m in session.messages):
            raise ForkError("edit_request_conflict")
        target = find_fork_input(history, source_id)
        if target is None:
            raise ForkError("edit_source_changed")
        ordinal, position, fact = target
        original_text = _plain_fork_text({**fact.content, "role": "user", "content": fact.content.get("text")})
        if fact.content.get("input_id") or fact.turn_id:
            matches = (
                i for i, m in enumerate(session.messages) if m.get("role") == "user" and not is_hidden_history_message(m)
                and (m.get("input_id") == source_id or (not m.get("input_id") and fact.turn_id and m.get("webui_turn_id") == fact.turn_id))
            )
            boundary = next(matches, None)
            if next(matches, None) is not None:
                raise ForkError("edit_source_changed")
        else:
            boundary = history_prefix_boundary(session, history.user_count_before(ordinal, position))
        if boundary is None or boundary >= len(session.messages):
            raise ForkError("edit_source_changed")
        original = session.messages[boundary]
        if (_plain_fork_text(original) != original_text or original.get("webui_turn_id") != fact.turn_id
                or (original.get("input_id") and original["input_id"] != source_id)):
            raise ForkError("edit_source_changed")
        retired_turn_ids.extend(history.retired_turn_ids(ordinal, position))
        event = build_user_transcript_event(chat_id, text)
        assert event is not None
        gateway.transcripts.prepare_event(chat_id, event, metadata=message.metadata, phase="user")
        event["created_at_ms"] = int(message.timestamp.timestamp() * 1000)
        return boundary, ordinal, position, fact_from_record(event)

    async def accepted(session: Session) -> None:
        nonlocal committed
        committed = True
        # Send the regular latest page on the wire. The retained prefix stays
        # in SQLite and can be paged by the same cursor as after a reconnect.
        body = await manager.state.project_history(key, lambda history: build_webui_thread_response(
            key, history=history, limit=40,
            session_messages_loader=lambda: session.messages,
            session_version_loader=lambda: history.session_version,
        ))
        assert body is not None
        body["history_generation"] = session.generation
        body["active_turn_id"] = turn_id
        body["has_pending_tool_calls"] = True
        await channel.announce_webui_history_replacement(
            chat_id, body, retired_turn_ids=retired_turn_ids, previous_generation=previous_generation,
        )

    try:
        await gateway.fork_in_place(message, source_id, locate, accepted)
    finally:
        if not committed:
            clear_websocket_turn_if_current(chat_id, queued_owner)
    return {"accepted": True, "turn_id": turn_id}
