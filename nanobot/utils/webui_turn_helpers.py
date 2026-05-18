"""Outbound helpers for the WebSocket/WebUI wire contract.

AgentLoop uses these without importing a concrete channel plugin; only
``channel == "websocket"`` messages are affected.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.session.goal_state import goal_state_ws_blob
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.helpers import truncate_text
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
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
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
        return False

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


async def publish_turn_run_status(bus: MessageBus, msg: InboundMessage, status: str) -> None:
    """Notify WebSocket clients while a user turn is executing (timing strip)."""
    if msg.channel != "websocket":
        return
    cid = str(msg.chat_id)
    meta: dict[str, Any] = {
        **dict(msg.metadata or {}),
        "_goal_status": True,
        "goal_status": status,
    }
    if status == "running":
        t0 = time.time()
        meta["started_at"] = t0
        _WEBSOCKET_TURN_WALL_STARTED_AT[cid] = t0
    else:
        _WEBSOCKET_TURN_WALL_STARTED_AT.pop(cid, None)
    await bus.publish_outbound(
        OutboundMessage(
            channel=msg.channel,
            chat_id=cid,
            content="",
            metadata=meta,
        ),
    )


def build_bus_progress_callback(
    bus: MessageBus,
    msg: InboundMessage,
) -> Callable[..., Awaitable[None]]:
    """Return the bus progress callback for agent runtime events."""

    async def _publish_progress(
        content: str,
        *,
        tool_hint: bool = False,
        tool_events: list[dict[str, Any]] | None = None,
        file_edit_events: list[dict[str, Any]] | None = None,
        reasoning: bool = False,
        reasoning_end: bool = False,
    ) -> None:
        meta = dict(msg.metadata or {})
        meta["_progress"] = True
        meta["_tool_hint"] = tool_hint
        if reasoning:
            meta["_reasoning_delta"] = True
        if reasoning_end:
            meta["_reasoning_end"] = True
        if tool_events:
            meta["_tool_events"] = tool_events
        if file_edit_events:
            meta["_file_edit_events"] = file_edit_events
        await bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
                metadata=meta,
            )
        )

    if msg.channel == "websocket":
        async def _websocket_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict[str, Any]] | None = None,
            file_edit_events: list[dict[str, Any]] | None = None,
            reasoning: bool = False,
            reasoning_end: bool = False,
        ) -> None:
            await _publish_progress(
                content,
                tool_hint=tool_hint,
                tool_events=tool_events,
                file_edit_events=file_edit_events,
                reasoning=reasoning,
                reasoning_end=reasoning_end,
            )

        return _websocket_progress

    async def _bus_progress(
        content: str,
        *,
        tool_hint: bool = False,
        tool_events: list[dict[str, Any]] | None = None,
        reasoning: bool = False,
        reasoning_end: bool = False,
    ) -> None:
        await _publish_progress(
            content,
            tool_hint=tool_hint,
            tool_events=tool_events,
            reasoning=reasoning,
            reasoning_end=reasoning_end,
        )

    return _bus_progress


@dataclass
class WebuiTurnCoordinator:
    """Own the WebUI/WebSocket wire details that hang off AgentLoop turns."""

    bus: MessageBus
    sessions: SessionManager
    schedule_background: Callable[[Awaitable[None]], None]
    _title_contexts: dict[str, LLMRuntime] = field(default_factory=dict)

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

    async def publish_run_status(self, msg: InboundMessage, status: str) -> None:
        await publish_turn_run_status(self.bus, msg, status)

    async def handle_turn_end(
        self,
        msg: InboundMessage,
        *,
        session_key: str,
        latency_ms: int | None,
    ) -> None:
        if msg.channel != "websocket":
            return

        turn_metadata: dict[str, Any] = {**msg.metadata, "_turn_end": True}
        if latency_ms is not None:
            turn_metadata["latency_ms"] = int(latency_ms)
        session = self.sessions.get_or_create(session_key)
        turn_metadata["goal_state"] = goal_state_ws_blob(session.metadata)
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content="",
            metadata=turn_metadata,
        ))
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
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="",
                    metadata={
                        **msg.metadata,
                        "_session_updated": True,
                        "_session_update_scope": "metadata",
                    },
                ))

        self.schedule_background(_generate_title_and_notify())
