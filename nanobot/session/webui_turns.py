"""Session turn helpers for WebUI-capable WebSocket sessions."""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.bus import progress as bus_progress
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import (
    GoalStateSyncEvent,
    GoalStatusEvent,
    RuntimeModelUpdatedEvent,
    SessionUpdatedEvent,
    TurnEndEvent,
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
)
from nanobot.providers.base import LLMProvider
from nanobot.session.automation_turns import is_automation_history_message
from nanobot.session.goal_state import goal_state_ws_blob
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.helpers import strip_think, truncate_text
from nanobot.utils.llm_runtime import LLMRuntime

WEBUI_SESSION_METADATA_KEY = "webui"
WEBUI_TITLE_METADATA_KEY = "title"
WEBUI_TITLE_USER_EDITED_METADATA_KEY = "title_user_edited"
TITLE_MAX_CHARS = 60
TITLE_GENERATION_MAX_TOKENS = 96
TITLE_GENERATION_REASONING_EFFORT = "none"

# Wall-clock turn start per ``chat_id`` (websocket only). Survives browser refresh while the
# gateway process stays up; cleared on idle/stop and implicitly dropped on restart.
_WEBSOCKET_TURN_WALL_STARTED_AT: dict[str, float] = {}


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
        if is_automation_history_message(message):
            continue
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
) -> bool:
    """Generate and persist a short title for WebUI-owned sessions only."""
    session = sessions.get_or_create(session_key)
    if session.metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
        return False
    if session.metadata.get(WEBUI_TITLE_USER_EDITED_METADATA_KEY) is True:
        return False
    current_title = session.metadata.get(WEBUI_TITLE_METADATA_KEY)
    if isinstance(current_title, str) and current_title.strip():
        cleaned_current_title = clean_generated_title(current_title)
        if cleaned_current_title:
            if cleaned_current_title != current_title:
                session.metadata[WEBUI_TITLE_METADATA_KEY] = cleaned_current_title
                sessions.save(session)
            return False
        session.metadata.pop(WEBUI_TITLE_METADATA_KEY, None)

    user_text, assistant_text = _title_inputs(session)
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
    session.metadata[WEBUI_TITLE_METADATA_KEY] = title
    sessions.save(session)
    return True


async def maybe_generate_webui_title_after_turn(
    *,
    channel: str,
    metadata: dict[str, Any],
    sessions: SessionManager,
    session_key: str,
    provider: LLMProvider,
    model: str,
) -> bool:
    if channel != "websocket" or metadata.get(WEBUI_SESSION_METADATA_KEY) is not True:
        return False
    return await maybe_generate_webui_title(
        sessions=sessions,
        session_key=session_key,
        provider=provider,
        model=model,
    )


def websocket_turn_wall_started_at(chat_id: str) -> float | None:
    """Return ``time.time()`` when the active user turn began, if still running."""
    return _WEBSOCKET_TURN_WALL_STARTED_AT.get(chat_id)


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
        _WEBSOCKET_TURN_WALL_STARTED_AT[cid] = t0
    else:
        _WEBSOCKET_TURN_WALL_STARTED_AT.pop(cid, None)
    await bus.publish_outbound(
        outbound_message_for_event(
            channel=msg.channel,
            chat_id=cid,
            event=GoalStatusEvent(status=status, started_at=started_at_event),
            metadata=msg.metadata,
        ),
    )

@dataclass
class WebuiTurnCoordinator:
    """Translate generic runtime events into WebUI/WebSocket wire messages."""

    bus: MessageBus
    sessions: SessionManager
    schedule_background: Callable[[Awaitable[None]], None]
    _title_contexts: dict[str, LLMRuntime] = field(default_factory=dict)

    def subscribe(self, runtime_events: RuntimeEventBus) -> Callable[[], None]:
        """Subscribe this coordinator to runtime events."""
        unsubscribe = [
            runtime_events.subscribe(
                self._handle_session_turn_started,
                SessionTurnStarted,
            ),
            runtime_events.subscribe(
                self._handle_run_status_changed,
                TurnRunStatusChanged,
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

    async def _handle_turn_completed_event(self, event: TurnCompleted) -> None:
        if not self._is_websocket_event(event.context):
            return
        msg = self._ctx_msg(event.context)
        await self.handle_turn_end(
            msg,
            session_key=event.context.session_key,
            latency_ms=event.latency_ms,
        )
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

    def capture_title_context(
        self,
        session_key: str,
        msg: InboundMessage,
        llm: LLMRuntime,
    ) -> None:
        if msg.channel == "websocket" and msg.metadata.get("webui") is True:
            self._title_contexts[session_key] = llm

    def discard(self, session_key: str) -> None:
        self._title_contexts.pop(session_key, None)

    async def publish_run_status(
        self,
        msg: InboundMessage,
        status: str,
        *,
        started_at: float | None = None,
    ) -> None:
        await publish_turn_run_status(self.bus, msg, status, started_at=started_at)

    async def handle_turn_end(
        self,
        msg: InboundMessage,
        *,
        session_key: str,
        latency_ms: int | None,
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
                ),
                metadata=msg.metadata,
            )
        )
        self._schedule_title_update(msg, session_key=session_key)

    def _schedule_title_update(self, msg: InboundMessage, *, session_key: str) -> None:
        title_context = self._title_contexts.pop(session_key, None)
        if msg.metadata.get("webui") is not True or title_context is None:
            return

        async def _generate_title_and_notify(
            title_llm: LLMRuntime = title_context,
        ) -> None:
            generated = await maybe_generate_webui_title_after_turn(
                channel=msg.channel,
                metadata=msg.metadata,
                sessions=self.sessions,
                session_key=session_key,
                provider=title_llm.provider,
                model=title_llm.model,
            )
            if generated:
                await self._publish_session_metadata_updated(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    metadata=msg.metadata,
                )

        self.schedule_background(_generate_title_and_notify())

    def _schedule_title_update_from_event(self, event: TurnCompleted) -> None:
        title_context = event.runtime
        if (
            event.context.metadata.get("webui") is not True
            or title_context is None
            or not isinstance(title_context, LLMRuntime)
        ):
            return

        async def _generate_title_and_notify(
            title_llm: LLMRuntime = title_context,
        ) -> None:
            generated = await maybe_generate_webui_title_after_turn(
                channel=event.context.channel,
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
