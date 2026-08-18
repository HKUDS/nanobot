"""Discovery and delivery tools for communication between sessions."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import RequestContext, ToolContext, current_request_context
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.runtime_context import RuntimeContextBlock
from nanobot.session.manager import SessionManager
from nanobot.session.session_handles import SessionHandleDirectory, SessionHandleDirectoryProtocol
from nanobot.session.session_messages import (
    MAX_REPLY_TIMEOUT_SECONDS,
    MIN_REPLY_TIMEOUT_SECONDS,
    SESSION_MESSAGE_METADATA_KEY,
    SESSION_MESSAGE_SENDER_ID,
    SESSION_REPLY_TIMEOUT_METADATA_KEY,
    SESSION_REPLY_TIMEOUT_SENDER_ID,
    SessionMessageEndpoint,
    SessionMessageEnvelope,
    SessionMessageError,
    SessionMessageSourceEndpoint,
    SessionReplyTimeoutEnvelope,
    is_persisted_webui_session,
    normalize_session_handle,
    session_message_envelope,
    session_reply_timeout_envelope,
)
from nanobot.webui.transcript import normalize_session_handles_metadata

_RATE_LIMIT_WINDOW_SECONDS = 60.0


class _CancelHandle(Protocol):
    def cancel(self) -> None: ...


@dataclass(slots=True)
class _PendingReply:
    timeout_seconds: int
    request: SessionMessageEnvelope
    timer: _CancelHandle | None = None


@tool_parameters(tool_parameters_schema())
class ListSessionsTool(Tool):
    """List addressable session handles without exposing session data."""

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions
        self._directory = SessionHandleDirectory(sessions)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        if ctx.sessions is None:
            raise RuntimeError("ListSessionsTool requires an initialized session manager")
        return cls(ctx.sessions)

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.sessions is not None

    @property
    def name(self) -> str:
        return "list_sessions"

    @property
    def description(self) -> str:
        return "List other sessions as @handles."

    @property
    def read_only(self) -> bool:
        return True

    def runtime_context_provider(self):
        return self._provide_runtime_context

    async def _provide_runtime_context(
        self,
        request: RequestContext,
    ) -> RuntimeContextBlock | None:
        if not request.session_key:
            return None
        handle = await asyncio.to_thread(
            self._directory.handle_for_session,
            request.session_key,
        )
        if handle is None:
            return None
        lines = [f"Your handle: @{handle.name}."]
        mentions = [
            f"@{mention['name']}"
            for mention in normalize_session_handles_metadata(
                request.metadata.get("session_handles")
            )
        ]
        if mentions:
            lines.append("Mentioned sessions: " + ", ".join(mentions) + ".")
        return RuntimeContextBlock(source="session_handle", content="\n".join(lines))

    async def execute(self, **kwargs: Any) -> str:
        request = current_request_context()
        if request is None or not request.session_key:
            return ToolResult.error("Error: session discovery context is unavailable")
        handles = await asyncio.to_thread(
            self._list_handles,
            request.session_key,
        )
        return json.dumps(handles, ensure_ascii=True)

    def _list_handles(self, source_session_key: str) -> list[str]:
        session_keys: list[str] = []
        for row in self._sessions.list_sessions():
            raw_key = row.get("key")
            if not isinstance(raw_key, str) or not raw_key.strip():
                continue
            session_keys.append(raw_key)

        # Handle provisioning is registry housekeeping, not a conversation
        # mutation. Every persisted session has an identity independently of UI.
        self._directory.ensure_many(session_keys)
        allowed = set(session_keys)
        return [
            f"@{handle.name}"
            for handle in self._directory.list_all()
            if handle.session_key in allowed and handle.session_key != source_session_key
        ]


@tool_parameters(
    tool_parameters_schema(
        to=StringSchema("Target @handle."),
        content=StringSchema("Message to send."),
        expect_reply=BooleanSchema(description="Expect a reply."),
        reply_timeout_seconds=IntegerSchema(
            description="Reply timeout; required with expect_reply.",
            minimum=MIN_REPLY_TIMEOUT_SECONDS,
            maximum=MAX_REPLY_TIMEOUT_SECONDS,
        ),
        required=["to", "content", "expect_reply"],
    )
)
class SendSessionMessageTool(Tool):
    """Send text to another session."""

    def __init__(
        self,
        *,
        sessions: SessionManager,
        bus: MessageBus,
        directory: SessionHandleDirectoryProtocol | None = None,
        max_messages_per_minute: int = 6,
        schedule_later: Callable[[float, Callable[[], None]], _CancelHandle] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._sessions = sessions
        self._bus = bus
        self._directory = directory or SessionHandleDirectory(sessions)
        self._max_messages_per_minute = max_messages_per_minute
        self._schedule_later = schedule_later
        self._clock = clock or time.monotonic
        self._sent_at: dict[str, deque[float]] = {}
        self._pending_replies: dict[tuple[str, str], _PendingReply] = {}
        self._expiry_tasks: set[asyncio.Task[None]] = set()
        self._send_lock = asyncio.Lock()

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        if ctx.sessions is None or ctx.bus is None:
            raise RuntimeError("Session messaging requires a session manager and message bus")
        return cls(
            sessions=ctx.sessions,
            bus=ctx.bus,
            max_messages_per_minute=ctx.config.max_session_messages_per_minute,
        )

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.sessions is not None and ctx.bus is not None

    @property
    def name(self) -> str:
        return "send_session_message"

    @property
    def description(self) -> str:
        return "Send a message to another session by @handle."

    def runtime_context_provider(self):
        return self._provide_runtime_context

    async def _provide_runtime_context(
        self,
        request: RequestContext,
    ) -> RuntimeContextBlock | None:
        envelope = session_message_envelope(request.metadata)
        if envelope is not None:
            source = f"@{envelope['source']['name']}"
            content = f"Message from {source}."
            if envelope["expect_reply"]:
                content += " Reply with send_session_message."
            return RuntimeContextBlock(
                source="session_collaboration",
                content=content,
            )

        timeout = session_reply_timeout_envelope(request.metadata)
        if timeout is None:
            return None
        session = f"@{timeout['target']['name']}"
        seconds = timeout["timeout_seconds"]
        return RuntimeContextBlock(
            source="session_collaboration",
            content=f"No reply from {session} after {seconds}s.",
        )

    async def execute(
        self,
        to: str,
        content: str,
        expect_reply: bool,
        reply_timeout_seconds: int | None = None,
        **kwargs: Any,
    ) -> str:
        from nanobot.utils.helpers import strip_think

        request = current_request_context()
        if (
            request is None
            or not request.session_key
        ):
            return ToolResult.error("Error: session messaging context is unavailable")
        try:
            target_handle = await self.enqueue(
                source_session_key=request.session_key,
                target_handle=to,
                content=strip_think(content),
                expect_reply=expect_reply,
                reply_timeout_seconds=reply_timeout_seconds,
            )
        except SessionMessageError as exc:
            return ToolResult.error(f"Error: {exc}")
        if expect_reply:
            return f"Sent to {target_handle}; reply expected within {reply_timeout_seconds}s. End the turn."
        return f"Sent to {target_handle}."

    async def enqueue(
        self,
        *,
        source_session_key: str,
        target_handle: str,
        content: str,
        expect_reply: bool,
        reply_timeout_seconds: int | None = None,
    ) -> str:
        """Publish one message to an existing target session."""
        timeout_seconds = self._validate_reply_timeout(
            expect_reply,
            reply_timeout_seconds,
        )
        lookup_name = normalize_session_handle(target_handle)
        source = await asyncio.to_thread(
            self._directory.handle_for_session,
            source_session_key,
        )
        if source is None:
            raise SessionMessageError("source_not_found", "source session was not found")
        target = await asyncio.to_thread(self._directory.resolve, lookup_name)
        if target is None:
            raise SessionMessageError("target_not_found", f"session @{lookup_name} was not found")

        source_endpoint: SessionMessageSourceEndpoint = {
            "name": source.name,
            "session_key": source.session_key,
            "handle_id": source.id,
            "color_slot": source.color_slot,
        }
        target_endpoint: SessionMessageEndpoint = {
            "name": target.name,
            "session_key": target.session_key,
        }
        envelope: SessionMessageEnvelope = {
            "message_id": uuid4().hex,
            "created_at_ms": int(time.time() * 1000),
            "expect_reply": expect_reply,
            "source": source_endpoint,
            "target": target_endpoint,
        }
        reverse_wait_key = (target.session_key, source.session_key)
        wait_key = (source.session_key, target.session_key)

        async with self._send_lock:
            target_session = await asyncio.to_thread(
                self._sessions.read_session_metadata,
                target.session_key,
            )
            if target_session is None:
                raise SessionMessageError("target_not_found", "target session is not persisted")

            now = self._clock()
            sent_at = self._sent_at.setdefault(source.session_key, deque())
            cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
            while sent_at and sent_at[0] <= cutoff:
                sent_at.popleft()
            if len(sent_at) >= self._max_messages_per_minute:
                raise SessionMessageError(
                    "rate_limited",
                    "session message rate limit reached "
                    f"({self._max_messages_per_minute} per minute)",
                )

            channel = "system"
            chat_id = target.session_key
            if is_persisted_webui_session(target.session_key, target_session):
                channel = "websocket"
                chat_id = target.session_key.split(":", 1)[1]
            await self._bus.publish_inbound(InboundMessage(
                channel=channel,
                sender_id=SESSION_MESSAGE_SENDER_ID,
                chat_id=chat_id,
                content=content,
                metadata={SESSION_MESSAGE_METADATA_KEY: envelope},
                session_key_override=target.session_key,
                require_existing_session=True,
            ))
            sent_at.append(now)
            self._cancel_pending_reply(reverse_wait_key)
            if timeout_seconds is not None:
                self._cancel_pending_reply(wait_key)
                self._schedule_pending_reply(
                    wait_key,
                    timeout_seconds=timeout_seconds,
                    request=envelope,
                )

        return f"@{target.name}"

    @staticmethod
    def _validate_reply_timeout(
        expect_reply: bool,
        reply_timeout_seconds: int | None,
    ) -> int | None:
        if not expect_reply:
            if reply_timeout_seconds is not None:
                raise SessionMessageError(
                    "unexpected_reply_timeout",
                    "reply_timeout_seconds requires expect_reply=true",
                )
            return None
        if (
            reply_timeout_seconds is None
            or not MIN_REPLY_TIMEOUT_SECONDS
            <= reply_timeout_seconds
            <= MAX_REPLY_TIMEOUT_SECONDS
        ):
            raise SessionMessageError(
                "invalid_reply_timeout",
                "expect_reply=true requires reply_timeout_seconds between "
                f"{MIN_REPLY_TIMEOUT_SECONDS} and {MAX_REPLY_TIMEOUT_SECONDS}",
            )
        return reply_timeout_seconds

    def _cancel_pending_reply(self, key: tuple[str, str]) -> None:
        pending = self._pending_replies.pop(key, None)
        if pending is not None and pending.timer is not None:
            pending.timer.cancel()

    def _schedule_pending_reply(
        self,
        key: tuple[str, str],
        *,
        timeout_seconds: int,
        request: SessionMessageEnvelope,
    ) -> None:
        pending = _PendingReply(
            timeout_seconds=timeout_seconds,
            request=request,
        )
        self._pending_replies[key] = pending

        def expire() -> None:
            task = asyncio.create_task(self._expire_pending_reply(key, pending))
            self._expiry_tasks.add(task)
            task.add_done_callback(self._expiry_tasks.discard)

        schedule_later = self._schedule_later or asyncio.get_running_loop().call_later
        pending.timer = schedule_later(float(timeout_seconds), expire)

    async def _expire_pending_reply(
        self,
        key: tuple[str, str],
        expected: _PendingReply,
    ) -> None:
        async with self._send_lock:
            if self._pending_replies.get(key) is not expected:
                return
            self._pending_replies.pop(key, None)
            envelope: SessionReplyTimeoutEnvelope = {
                **expected.request,
                "timeout_seconds": expected.timeout_seconds,
            }
            waiter_key = expected.request["source"]["session_key"]
            await self._bus.publish_inbound(InboundMessage(
                channel="system",
                sender_id=SESSION_REPLY_TIMEOUT_SENDER_ID,
                chat_id=waiter_key,
                content="",
                metadata={SESSION_REPLY_TIMEOUT_METADATA_KEY: envelope},
                session_key_override=waiter_key,
                require_existing_session=True,
            ))
