from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from loguru import logger

from nanobot.bus.events import INBOUND_META_LOCAL_MEDIA, InboundMessage
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_HISTORY_META,
    WEBUI_QUOTE_SOURCE,
    public_history_message,
)
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.display_history import HistoryFact, HistoryReader
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import Session, history_prefix_boundary
from nanobot.session.state import EditError
from nanobot.session.webui_turns import (
    clear_websocket_turn_if_current,
    register_queued_websocket_turn_if_idle,
)
from nanobot.webui.attachments import inspect_local_attachment
from nanobot.webui.history import MODEL_PROJECTED_INPUT, fact_from_record
from nanobot.webui.metadata import WEBSOCKET_TURN_OWNER_METADATA_KEY
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key
from nanobot.webui.transcript import (
    build_user_transcript_event,
    find_history_input,
)

if TYPE_CHECKING:
    from nanobot.webui.gateway_services import GatewayServices


class MessageEditHost(Protocol):
    gateway: GatewayServices

    async def invalidate_history(self, chat_id: str) -> None: ...


def _check_metadata(message: Mapping[str, Any]) -> None:
    if any(message.get(key) for key in (
        "_hidden_history", "_command", "session_message", "injected_event", "source", "automation",
        "automation_id", "cron_job_id", "_automation_turn", "_user_shell",
    )):
        raise EditError("edit_special_message")
    if any(message.get(key) for key in ("cli_apps", "mcp_presets", "session_mentions")):
        raise EditError("edit_mentions_unsupported")
    context = message.get(RUNTIME_CONTEXT_HISTORY_META)
    sources: list[str] = cast(dict[str, Any], context).get("sources", []) if isinstance(context, dict) else []
    if WEBUI_QUOTE_SOURCE in sources:
        raise EditError("edit_context_unsupported")
    if any(source in sources for source in ("session_mentions", "cli_apps", "mcp_presets")):
        raise EditError("edit_mentions_unsupported")
    if "session_message" in sources:
        raise EditError("edit_special_message")


def _check_text(text: str) -> None:
    if text.startswith("> [!QUOTE]"):
        raise EditError("edit_context_unsupported")
    if text.lstrip().startswith(("/", "!")):
        raise EditError("edit_commands_unsupported")
    if re.search(r"(^|\s)@[\w-]+", text):
        raise EditError("edit_mentions_unsupported")


def _paths(record: Mapping[str, Any], key: str) -> list[str]:
    raw = record.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(p, str) and p for p in cast(list[object], raw)):
        raise EditError("edit_attachments_unavailable")
    return cast(list[str], raw)


def _restore_media(
    gateway: GatewayServices, session: Session, original: dict[str, Any], fact: HistoryFact, message: InboundMessage,
) -> None:
    display = fact.content
    caption = display.get("text")
    if not isinstance(caption, str):
        raise EditError("edit_plain_text_only")
    _check_text(caption)
    # A model-only fork may have document references rendered into its text
    # but no original file list. Ordinary user captions are never interpreted.
    if display.get(MODEL_PROJECTED_INPUT) and caption.rpartition("\n")[2].startswith("[Attachment: "):
        raise EditError("edit_attachments_unavailable")
    paths = _paths(display, "media_paths")
    local = _paths(display, INBOUND_META_LOCAL_MEDIA)
    if (display.get("media_urls") or display.get("media") or original.get("media_urls") or original.get("media_paths")
            or local != _paths(original, INBOUND_META_LOCAL_MEDIA) or not set(local).issubset(paths)
            or not set(_paths(original, "media")).issubset(paths)):
        raise EditError("edit_attachments_unavailable")
    if not paths:
        content = public_history_message(original).get("content")
        if not isinstance(content, str) or not caption.strip():
            raise EditError("edit_plain_text_only")
        if content != caption:
            raise EditError("edit_source_changed")
        if not message.content.strip():
            raise EditError("edit_invalid_request")
        return

    # The stable input identity ties the model row to the display fact. Only
    # the latter retains the ordered paths and the caption before preprocessing.
    if not (fact.turn_id or display.get("input_id")):
        raise EditError("edit_attachments_unavailable")
    store = gateway.uploads.store
    try:
        store.check_committed_paths([p for p in paths if p not in local])
        if local:
            raw_scope = session.metadata.get(WORKSPACE_SCOPE_METADATA_KEY)
            fallback = gateway.workspaces.restricted_default_scope()
            scope = gateway.workspaces.scope_for_indexed_metadata(
                raw_scope, scope_present=raw_scope is not None, default_scope=fallback,
            )
            # Never use the sidebar fallback to authorize a deleted or missing project.
            if scope is fallback or scope.metadata() != raw_scope or any(
                inspect_local_attachment(p, scope=scope, limits=store.limits)["path"] != p for p in local
            ):
                raise ValueError("local attachment scope or path changed")
            message.metadata[WORKSPACE_SCOPE_METADATA_KEY] = scope.metadata()
            message.metadata[INBOUND_META_LOCAL_MEDIA] = local
    except (ValueError, OSError, RuntimeError) as exc:
        raise EditError("edit_attachments_unavailable") from exc
    message.media = paths


async def edit_webui_message(
    channel: MessageEditHost, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep the prefix before the selected input in this chat and resume from the new text."""

    gateway = channel.gateway
    chat_id, text, turn_id, source_id = (
        payload.get("chat_id"), payload.get("text"), payload.get("turn_id"), payload.get("source_id"),
    )
    if (not is_valid_webui_chat_id(chat_id)
            or not isinstance(text, str)
            or not isinstance(turn_id, str) or not turn_id or len(turn_id) > 128
            or not isinstance(source_id, str) or not source_id):
        raise EditError("edit_invalid_request")
    if gateway.ingress.validate_text(text) is not None:
        raise EditError("edit_text_too_large")
    _check_text(text)
    if gateway.session_manager is None or gateway.enqueue_if_idle is None:
        raise EditError("edit_unavailable")
    key = webui_session_key(chat_id)
    manager = gateway.session_manager
    queued_owner = register_queued_websocket_turn_if_idle(chat_id, turn_id)
    message = InboundMessage(
        channel="websocket", chat_id=chat_id, sender_id="webui", content=text,
        metadata={"webui": True, "_wants_stream": True, "webui_turn_id": turn_id,
                  WEBSOCKET_TURN_OWNER_METADATA_KEY: queued_owner},
    )
    committed = False

    def locate(session: Session, history: HistoryReader) -> tuple[int, int, int, HistoryFact]:
        if history.has_input(f"user:{turn_id}") or any(m.get("webui_turn_id") == turn_id for m in session.messages):
            raise EditError("edit_request_conflict")
        target = find_history_input(history, source_id)
        if target is None:
            raise EditError("edit_source_changed")
        ordinal, position, fact = target
        _check_metadata(fact.content)
        if fact.content.get("input_id") or fact.turn_id:
            matches = (
                i for i, m in enumerate(session.messages) if m.get("role") == "user" and not is_hidden_history_message(m)
                and (m.get("input_id") == source_id or (not m.get("input_id") and fact.turn_id and m.get("webui_turn_id") == fact.turn_id))
            )
            boundary = next(matches, None)
            if next(matches, None) is not None:
                raise EditError("edit_source_changed")
        else:
            boundary = history_prefix_boundary(session, history.user_count_before(ordinal, position))
        if boundary is None or boundary >= len(session.messages):
            raise EditError("edit_source_changed")
        original = session.messages[boundary]
        if (original.get("role") != "user" or original.get("webui_turn_id") != fact.turn_id
                or (original.get("input_id") and original["input_id"] != source_id)):
            raise EditError("edit_source_changed")
        _check_metadata(original)
        _restore_media(gateway, session, original, fact, message)
        event = build_user_transcript_event(
            chat_id, text, media_paths=message.media, local_media_paths=message.metadata.get(INBOUND_META_LOCAL_MEDIA),
        )
        assert event is not None
        gateway.transcripts.prepare_event(chat_id, event, metadata=message.metadata, phase="user")
        event["created_at_ms"] = int(message.timestamp.timestamp() * 1000)
        return boundary, ordinal, position, fact_from_record(event)

    async def prepare() -> bool:
        nonlocal committed
        session = await manager.state.replace_input(key, source_id, message, locate)
        if session is None:  # Exact retry of the last accepted edit.
            return False
        message.session_generation = session.generation
        committed = True
        try:
            await channel.invalidate_history(chat_id)
        except Exception:
            # A disconnected subscriber must not prevent the durable input from running.
            logger.exception("Unable to announce history invalidation for {}", key)
        return True

    try:
        if queued_owner is None or not await gateway.enqueue_if_idle(message, prepare):
            # Only an exact retry can succeed while another turn owns the session.
            await manager.state.replace_input(key, source_id, message, None)
    finally:
        if queued_owner is not None and not committed:
            clear_websocket_turn_if_current(chat_id, queued_owner)
    return {"accepted": True, "turn_id": turn_id}
