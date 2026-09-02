"""Session turn helpers for WebUI-capable WebSocket sessions."""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import uuid4

from loguru import logger

from nanobot.agent.tools.context import current_request_context
from nanobot.agent.turn_delivery import TurnRoute
from nanobot.bus import progress as bus_progress
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import (
    GoalStateSyncEvent,
    GoalStatusEvent,
    RuntimeModelUpdatedEvent,
    SessionUpdatedEvent,
    TurnEndEvent,
    TurnModelUpdatedEvent,
    UserInputEvent,
    outbound_message_for_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import (
    GoalStateChanged,
    RuntimeEventBus,
    RuntimeEventContext,
    RuntimeModelChanged,
    SessionTurnStarted,
    TurnCompleted,
    TurnRunStatusChanged,
    TurnRuntimeAdmitted,
    UserInputAccepted,
)
from nanobot.llm_usage.context import llm_usage_source
from nanobot.providers.base import LLMProvider, LLMUsage
from nanobot.providers.fallback_provider import FallbackModelObserver
from nanobot.runtime_context import public_history_message
from nanobot.session.goal_state import goal_state_ws_blob
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import Session, SessionManager
from nanobot.session.recovery import RecoveryCoordinator
from nanobot.session.session_handles import session_handle_for_name
from nanobot.session.session_messages import (
    SessionMessageEnvelope,
    session_message_envelope,
)
from nanobot.utils.helpers import strip_think, truncate_text
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui.metadata import (
    WEBSOCKET_TURN_OWNER_METADATA_KEY,
    WEBUI_TURN_METADATA_KEY,
)
from nanobot.webui.session_identity import is_webui_session_key
from nanobot.webui.transcript import append_session_message_input

WEBUI_SESSION_METADATA_KEY = "webui"
WEBUI_TITLE_METADATA_KEY = "title"
WEBUI_TITLE_USER_EDITED_METADATA_KEY = "title_user_edited"
TITLE_MAX_CHARS = 60
TITLE_GENERATION_MAX_TOKENS = 96
TITLE_GENERATION_REASONING_EFFORT = "none"

# Latest active turn projection per ``chat_id`` (websocket only). It survives browser refresh
# while the gateway process stays up and is implicitly dropped on restart.
_WEBSOCKET_TURN_WALL_STARTED_AT: dict[str, float] = {}
_WEBSOCKET_TURN_IDS: dict[str, str] = {}
_WEBSOCKET_TURN_OWNERS: dict[str, str] = {}


@dataclass(frozen=True)
class _WebsocketTurn:
    started_at: float
    turn_id: str | None
    transcript_persistence_failed: bool = False


# All in-flight lifecycle owners per chat, in admission order. The three maps
# above remain the latest-owner projection consumed by the HTTP API.
_WEBSOCKET_ACTIVE_TURNS: dict[str, dict[str, _WebsocketTurn]] = {}


def _session_message_public_metadata(
    envelope: SessionMessageEnvelope,
) -> dict[str, Any]:
    source = session_handle_for_name(
        envelope["source_session_key"],
        envelope["source_handle"],
    )
    return {
        "message_id": envelope["message_id"],
        "session": source.public_payload(),
    }


def _validated_llm_runtime(value: object) -> LLMRuntime | None:
    """Keep runtime-event consumers defensive if an external publisher violates the contract."""
    return value if isinstance(value, LLMRuntime) else None


def _sync_websocket_turn_projection(chat_id: str) -> None:
    turns = _WEBSOCKET_ACTIVE_TURNS.get(chat_id)
    if not turns:
        _WEBSOCKET_ACTIVE_TURNS.pop(chat_id, None)
        _WEBSOCKET_TURN_WALL_STARTED_AT.pop(chat_id, None)
        _WEBSOCKET_TURN_IDS.pop(chat_id, None)
        _WEBSOCKET_TURN_OWNERS.pop(chat_id, None)
        return

    owner = next(reversed(turns))
    turn = turns[owner]
    _WEBSOCKET_TURN_WALL_STARTED_AT[chat_id] = turn.started_at
    _WEBSOCKET_TURN_OWNERS[chat_id] = owner
    if turn.turn_id is None:
        _WEBSOCKET_TURN_IDS.pop(chat_id, None)
    else:
        _WEBSOCKET_TURN_IDS[chat_id] = turn.turn_id


def mark_webui_session(session: Session, metadata: dict[str, Any]) -> bool:
    """Persist a WebUI marker only when the inbound websocket frame opted in."""
    if metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
        return False
    session.metadata[WEBUI_SESSION_METADATA_KEY] = True
    return True


def clean_generated_title(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\s*(title|标题)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    text = text.strip().strip("\"'`“”‘’")
    text = strip_think(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.rstrip("。.!！?？,，;；:")
    if len(text) > TITLE_MAX_CHARS:
        text = text[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return text


def _title_inputs(session: Session) -> tuple[str, str]:
    user_text = ""
    assistant_text = ""
    for message in session.messages:
        if message.get("_command") is True:
            continue
        if is_hidden_history_message(message):
            continue
        message = public_history_message(message)
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        content = strip_think(content)
        if not content:
            continue
        if role == "user" and not user_text:
            user_text = content.strip()
        elif role == "assistant" and not assistant_text:
            assistant_text = content.strip()
        if user_text and assistant_text:
            break
    return user_text, assistant_text


def _latest_title_inputs(session: Session) -> tuple[str, str]:
    """Latest user/assistant texts, for turns executed on a shared session."""
    user_text = ""
    assistant_text = ""
    for message in reversed(session.messages):
        if message.get("_command") is True:
            continue
        if is_hidden_history_message(message):
            continue
        message = public_history_message(message)
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        content = strip_think(content)
        if not content:
            continue
        if role == "user" and not user_text:
            user_text = content.strip()
        elif role == "assistant" and not assistant_text:
            assistant_text = content.strip()
        if user_text and assistant_text:
            break
    return user_text, assistant_text


async def maybe_generate_webui_title(
    *,
    sessions: SessionManager,
    session_key: str,
    provider: LLMProvider,
    model: str,
    target_session_key: str | None = None,
) -> bool:
    """Generate and persist a short title for WebUI-owned sessions.

    ``session_key`` owns the conversation content. Under unified-session
    routing this is the shared session while WebUI renders per-chat sessions,
    so pass ``target_session_key`` to project the title onto that per-chat
    session instead of storing it on the shared one.
    """
    routed_session = sessions.get_or_create(session_key)
    target_is_routed = target_session_key is None or target_session_key == session_key
    if target_is_routed or target_session_key is None:
        target_session = routed_session
    else:
        target_session = sessions.get_or_create(target_session_key)
    if (
        routed_session.metadata.get(WEBUI_SESSION_METADATA_KEY) is not True
        and target_session.metadata.get(WEBUI_SESSION_METADATA_KEY) is not True
    ):
        return False
    if target_session.metadata.get(WEBUI_TITLE_USER_EDITED_METADATA_KEY) is True:
        return False
    current_title = target_session.metadata.get(WEBUI_TITLE_METADATA_KEY)
    if isinstance(current_title, str) and current_title.strip():
        cleaned_current_title = clean_generated_title(current_title)
        if cleaned_current_title:
            if cleaned_current_title != current_title:
                target_session.metadata[WEBUI_TITLE_METADATA_KEY] = cleaned_current_title
                sessions.save(target_session)
            return False
        target_session.metadata.pop(WEBUI_TITLE_METADATA_KEY, None)

    if target_is_routed:
        user_text, assistant_text = _title_inputs(routed_session)
    else:
        # Shared-session content mixes every channel; generation runs right
        # after this turn, so its exchange is the latest pair.
        user_text, assistant_text = _latest_title_inputs(routed_session)
    if not user_text:
        return False

    prompt = (
        "Generate a concise title for this chat.\n"
        "Rules:\n"
        "- Use the same language as the user when practical.\n"
        "- 3 to 8 words.\n"
        "- No quotes.\n"
        "- No punctuation at the end.\n"
        "- Return only the title.\n\n"
        f"User: {truncate_text(user_text, 1_000)}"
    )
    if assistant_text:
        prompt += f"\nAssistant: {truncate_text(assistant_text, 1_000)}"

    try:
        with llm_usage_source("system"):
            response = await provider.chat_with_retry(
                [
                    {
                        "role": "system",
                        "content": (
                            "You write short, neutral chat titles. "
                            "Return only the title text."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                model=model,
                max_tokens=TITLE_GENERATION_MAX_TOKENS,
                temperature=0.2,
                reasoning_effort=TITLE_GENERATION_REASONING_EFFORT,
                retry_mode="standard",
            )
    except Exception:
        logger.debug("Failed to generate webui session title for {}", session_key, exc_info=True)
        return False

    title = clean_generated_title(response.content)
    if not title or title.lower().startswith("error"):
        logger.debug(
            "WebUI title generation returned no usable title for {} (finish_reason={})",
            session_key,
            response.finish_reason,
        )
        return False
    target_session.metadata[WEBUI_TITLE_METADATA_KEY] = title
    sessions.save(target_session)
    return True


async def maybe_generate_webui_title_after_turn(
    *,
    channel: str,
    chat_id: str,
    metadata: dict[str, Any],
    sessions: SessionManager,
    session_key: str,
    provider: LLMProvider,
    model: str,
) -> bool:
    if channel != "websocket" or metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
        return False
    origin_session_key = f"{channel}:{chat_id}"
    return await maybe_generate_webui_title(
        sessions=sessions,
        session_key=session_key,
        provider=provider,
        model=model,
        target_session_key=(
            origin_session_key if origin_session_key != session_key else None
        ),
    )


def websocket_turn_wall_started_at(chat_id: str) -> float | None:
    """Return ``time.time()`` when the active user turn began, if still running."""
    return _WEBSOCKET_TURN_WALL_STARTED_AT.get(chat_id)


def websocket_turn_id(chat_id: str) -> str | None:
    """Return the WebUI identity of the active turn, when one was provided."""
    return _WEBSOCKET_TURN_IDS.get(chat_id)


def register_queued_websocket_turn_if_idle(
    chat_id: str,
    turn_id: str | None,
) -> str | None:
    """Track an accepted WebUI turn while it waits for AgentLoop admission."""
    if websocket_turn_wall_started_at(chat_id) is not None:
        return None
    owner = uuid4().hex
    _WEBSOCKET_ACTIVE_TURNS.setdefault(chat_id, {})[owner] = _WebsocketTurn(
        started_at=time.time(),
        turn_id=turn_id,
    )
    _sync_websocket_turn_projection(chat_id)
    return owner


def websocket_turn_owner_is_registered(
    chat_id: str,
    owner: str,
    turn_id: str | None,
) -> bool:
    """Return whether websocket ingress registered this owner for the turn."""
    turn = _WEBSOCKET_ACTIVE_TURNS.get(chat_id, {}).get(owner)
    return turn is not None and turn.turn_id == turn_id


def websocket_turn_transcript_persistence_failed(
    chat_id: str,
    owner: str | None = None,
) -> bool:
    """Return whether one active owner has an incomplete canonical transcript."""
    turns = _WEBSOCKET_ACTIVE_TURNS.get(chat_id)
    if not turns:
        return False
    selected_owner = owner or next(reversed(turns))
    turn = turns.get(selected_owner)
    return turn.transcript_persistence_failed if turn is not None else False


def mark_websocket_turn_transcript_persistence_failed(
    chat_id: str,
    owner: str | None,
) -> bool:
    """Keep a turn active when any canonical display event could not be written."""
    if not owner:
        return False
    turns = _WEBSOCKET_ACTIVE_TURNS.get(chat_id)
    if turns is None or owner not in turns:
        return False
    turns[owner] = replace(turns[owner], transcript_persistence_failed=True)
    return True


def clear_websocket_turn_if_current(
    chat_id: str,
    owner: str | None,
    *,
    preserve_persistence_failure: bool = False,
) -> bool:
    """Clear one lifecycle owner without disturbing concurrent turns for the chat."""
    if not owner:
        return False
    turns = _WEBSOCKET_ACTIVE_TURNS.get(chat_id)
    if turns is not None:
        if owner not in turns:
            return False
        if preserve_persistence_failure and turns[owner].transcript_persistence_failed:
            return False
        turns.pop(owner)
        _sync_websocket_turn_projection(chat_id)
        return True

    # Compatibility for callers/tests that populated the legacy projection
    # directly before the multi-owner registry existed.
    if (
        chat_id in _WEBSOCKET_TURN_WALL_STARTED_AT
        and _WEBSOCKET_TURN_OWNERS.get(chat_id) == owner
    ):
        _WEBSOCKET_TURN_WALL_STARTED_AT.pop(chat_id, None)
        _WEBSOCKET_TURN_IDS.pop(chat_id, None)
        _WEBSOCKET_TURN_OWNERS.pop(chat_id, None)
        return True
    return False


def clear_websocket_turns(chat_id: str) -> None:
    """Forget every in-process turn projection for a discarded chat."""
    _WEBSOCKET_ACTIVE_TURNS.pop(chat_id, None)
    _sync_websocket_turn_projection(chat_id)


def build_bus_progress_callback(
    bus: MessageBus,
    msg: InboundMessage,
) -> Callable[..., Awaitable[None]]:
    """Compatibility wrapper for the generic bus progress callback."""
    return bus_progress.build_bus_progress_callback(bus, msg)


async def publish_turn_run_status(
    bus: MessageBus,
    msg: InboundMessage,
    status: str,
    *,
    started_at: float | None = None,
) -> None:
    """Notify WebSocket clients while a user turn is executing (timing strip)."""
    if msg.channel != "websocket":
        return
    cid = str(msg.chat_id)
    started_at_event: float | None = None
    if status == "running":
        if isinstance(started_at, int | float) and started_at > 0:
            t0 = float(started_at)
        else:
            t0 = time.time()
        started_at_event = t0
        owner = msg.metadata.get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
        if not isinstance(owner, str) or not owner:
            owner = uuid4().hex
            msg.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] = owner
        turn_id = msg.metadata.get(WEBUI_TURN_METADATA_KEY)
        current_turn_id = turn_id if isinstance(turn_id, str) and turn_id else None
        turns = _WEBSOCKET_ACTIVE_TURNS.setdefault(cid, {})
        # Re-registration makes this owner the latest projection.
        turns.pop(owner, None)
        turns[owner] = _WebsocketTurn(started_at=t0, turn_id=current_turn_id)
        _sync_websocket_turn_projection(cid)
    await bus.publish_outbound(
        outbound_message_for_event(
            channel=msg.channel,
            chat_id=cid,
            event=GoalStatusEvent(status=status, started_at=started_at_event),
            metadata=msg.metadata,
        ),
    )

@dataclass(frozen=True)
class WebuiTurnRoutePolicy:
    """Expose independently dispatched agent turns to WebUI sessions."""

    sessions: SessionManager

    def __call__(
        self,
        msg: InboundMessage,
        session_key: str,
        route: TurnRoute,
    ) -> TurnRoute:
        """Make an independently dispatched agent turn visible in WebUI."""
        routed = route
        internal_user_input = msg.channel == "system" and msg.is_user_input
        if (
            (
                (
                    msg.channel == "system"
                    and msg.sender_id == "subagent"
                    and msg.metadata.get("injected_event") == "subagent_result"
                )
                or internal_user_input
            )
            and route.channel == "websocket"
        ):
            session = self.sessions.get_or_create(session_key)
            if session.metadata.get(WEBUI_SESSION_METADATA_KEY) is True:
                metadata = dict(route.metadata)
                turn_prefix = "session-input" if internal_user_input else "subagent"
                metadata.update({
                    WEBUI_SESSION_METADATA_KEY: True,
                    "_wants_stream": True,
                    WEBUI_TURN_METADATA_KEY: f"{turn_prefix}:{uuid4().hex}",
                })
                routed = replace(route, metadata=metadata, publish_lifecycle=True)

        if routed.channel == "websocket" and routed.publish_lifecycle:
            metadata = dict(routed.metadata)
            turn_id = metadata.get(WEBUI_TURN_METADATA_KEY)
            current_turn_id = turn_id if isinstance(turn_id, str) and turn_id else None
            queued_owner = metadata.get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            owner = (
                queued_owner
                if (
                    msg.channel == "websocket"
                    and isinstance(queued_owner, str)
                    and websocket_turn_owner_is_registered(
                        str(msg.chat_id),
                        queued_owner,
                        current_turn_id,
                    )
                )
                else uuid4().hex
            )
            metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] = owner
            routed = replace(routed, metadata=metadata)
            # Direct websocket turns publish their final idle transition from
            # the original input message. Carry the same server-owned identity
            # there, overwriting any untrusted client-supplied value.
            if msg.channel == "websocket":
                msg.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] = owner

        return routed


def build_webui_fallback_model_observer(bus: MessageBus) -> FallbackModelObserver:
    """Translate provider fallback choices into chat-scoped WebUI events."""

    async def _publish(model: str) -> None:
        context = current_request_context()
        if context is None or context.channel != "websocket":
            return
        chat_id = str(context.chat_id or "").strip()
        if not chat_id:
            return
        await bus.publish_outbound(
            outbound_message_for_event(
                channel=context.channel,
                chat_id=chat_id,
                event=TurnModelUpdatedEvent(
                    model=model,
                    model_preset=(
                        context.runtime.model_preset
                        if context.runtime is not None
                        else None
                    ),
                    fallback=True,
                ),
                metadata=context.metadata,
            )
        )

    return _publish


@dataclass
class WebuiTurnCoordinator:
    """Translate generic runtime events into WebUI/WebSocket wire messages."""

    bus: MessageBus
    sessions: SessionManager
    schedule_background: Callable[[Awaitable[None]], None]
    recovery: RecoveryCoordinator | None = None

    def subscribe(self, runtime_events: RuntimeEventBus) -> Callable[[], None]:
        """Subscribe this coordinator to runtime events."""
        unsubscribe = [
            runtime_events.subscribe(
                self._handle_user_input_accepted,
                UserInputAccepted,
            ),
            runtime_events.subscribe(
                self._handle_session_turn_started,
                SessionTurnStarted,
            ),
            runtime_events.subscribe(
                self._handle_run_status_changed,
                TurnRunStatusChanged,
            ),
            runtime_events.subscribe(
                self._handle_turn_runtime_admitted,
                TurnRuntimeAdmitted,
            ),
            runtime_events.subscribe(
                self._handle_turn_completed_event,
                TurnCompleted,
            ),
            runtime_events.subscribe(
                self._handle_goal_state_changed,
                GoalStateChanged,
            ),
            runtime_events.subscribe(
                self._handle_runtime_model_changed,
                RuntimeModelChanged,
            ),
        ]

        def _unsubscribe() -> None:
            for fn in reversed(unsubscribe):
                fn()

        return _unsubscribe

    @staticmethod
    def _ctx_msg(ctx: RuntimeEventContext) -> InboundMessage:
        return InboundMessage(
            channel=ctx.channel,
            sender_id="runtime",
            chat_id=ctx.chat_id,
            content="",
            metadata=dict(ctx.metadata or {}),
            session_key_override=ctx.session_key,
        )

    @staticmethod
    def _is_websocket_event(ctx: RuntimeEventContext) -> bool:
        return ctx.channel == "websocket"

    async def _handle_user_input_accepted(self, event: UserInputAccepted) -> None:
        envelope = session_message_envelope(event.context.metadata)
        session_key = event.context.session_key
        if (
            event.context.channel != "system"
            or envelope is None
            or envelope["target_session_key"] != session_key
            or not is_webui_session_key(session_key)
        ):
            return
        persisted = self.sessions.read_session_metadata(session_key)
        metadata_value: object = persisted.get("metadata") if persisted is not None else None
        metadata = (
            cast(dict[str, Any], metadata_value)
            if isinstance(metadata_value, dict)
            else None
        )
        if metadata is None or metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
            return
        public_metadata = _session_message_public_metadata(envelope)
        try:
            append_session_message_input(
                session_key,
                content=event.content,
                created_at_ms=envelope["created_at_ms"],
                session_message=public_metadata,
            )
        except (OSError, TypeError, ValueError):
            logger.warning(
                "Failed to persist session input {}",
                envelope["message_id"],
                exc_info=True,
            )
        await self.bus.publish_outbound(outbound_message_for_event(
            channel="websocket",
            chat_id=session_key.split(":", 1)[1],
            event=UserInputEvent(
                content=event.content,
                created_at_ms=envelope["created_at_ms"],
                provenance={"session_message": public_metadata},
            ),
        ))

    def _handle_session_turn_started(self, event: SessionTurnStarted) -> None:
        if not self._is_websocket_event(event.context):
            return
        session = self.sessions.get_or_create(event.context.session_key)
        mark_webui_session(session, event.context.metadata)

    async def _handle_run_status_changed(self, event: TurnRunStatusChanged) -> None:
        if not self._is_websocket_event(event.context):
            return
        await publish_turn_run_status(
            self.bus,
            self._ctx_msg(event.context),
            event.status,
            started_at=event.started_at,
        )

    async def _handle_turn_runtime_admitted(self, event: TurnRuntimeAdmitted) -> None:
        if not self._is_websocket_event(event.context):
            return
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel=event.context.channel,
                chat_id=event.context.chat_id,
                event=TurnModelUpdatedEvent(
                    model=event.runtime.model,
                    model_preset=event.runtime.model_preset,
                    context_window_tokens=event.runtime.context_window_tokens,
                ),
                metadata=event.context.metadata,
            )
        )

    async def _handle_turn_completed_event(self, event: TurnCompleted) -> None:
        if not self._is_websocket_event(event.context):
            return
        msg = self._ctx_msg(event.context)
        await self.handle_turn_end(
            msg,
            session_key=event.context.session_key,
            latency_ms=event.latency_ms,
            usage=event.usage,
            context_window_tokens=(
                event.runtime.context_window_tokens if event.runtime is not None else None
            ),
        )
        if self.recovery is not None:
            await self.recovery.turn_completed(event.context.session_key)
        self._schedule_title_update_from_event(event)

    async def _handle_goal_state_changed(self, event: GoalStateChanged) -> None:
        if not self._is_websocket_event(event.context):
            return
        cid = str(event.context.chat_id or "").strip()
        if not cid:
            return
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel=event.context.channel,
                chat_id=cid,
                event=GoalStateSyncEvent(
                    goal_state=goal_state_ws_blob(event.session_metadata),
                ),
                metadata=event.context.metadata,
            ),
        )

    async def _handle_runtime_model_changed(self, event: RuntimeModelChanged) -> None:
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel="websocket",
                chat_id="*",
                event=RuntimeModelUpdatedEvent(
                    model=event.model,
                    model_preset=event.model_preset,
                ),
            )
        )

    async def handle_turn_end(
        self,
        msg: InboundMessage,
        *,
        session_key: str,
        latency_ms: int | None,
        usage: LLMUsage | None = None,
        context_window_tokens: int | None = None,
    ) -> None:
        if msg.channel != "websocket":
            return

        session = self.sessions.get_or_create(session_key)
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel=msg.channel,
                chat_id=msg.chat_id,
                event=TurnEndEvent(
                    latency_ms=latency_ms,
                    goal_state=goal_state_ws_blob(session.metadata),
                    usage=usage,
                    context_window_tokens=context_window_tokens,
                ),
                metadata=msg.metadata,
            )
        )

    def _schedule_title_update_from_event(self, event: TurnCompleted) -> None:
        title_context = _validated_llm_runtime(event.runtime)
        if (
            event.context.metadata.get("webui") is not True
            or title_context is None
        ):
            return

        async def _generate_title_and_notify(
            title_llm: LLMRuntime = title_context,
        ) -> None:
            generated = await maybe_generate_webui_title_after_turn(
                channel=event.context.channel,
                chat_id=event.context.chat_id,
                metadata=event.context.metadata,
                sessions=self.sessions,
                session_key=event.context.session_key,
                provider=title_llm.provider,
                model=title_llm.model,
            )
            if generated:
                await self._publish_session_metadata_updated(
                    channel=event.context.channel,
                    chat_id=event.context.chat_id,
                    metadata=event.context.metadata,
                )

        self.schedule_background(_generate_title_and_notify())

    async def _publish_session_metadata_updated(
        self,
        *,
        channel: str,
        chat_id: str,
        metadata: dict[str, Any],
    ) -> None:
        await self.bus.publish_outbound(
            outbound_message_for_event(
                channel=channel,
                chat_id=chat_id,
                event=SessionUpdatedEvent(scope="metadata"),
                metadata=metadata,
            )
        )
