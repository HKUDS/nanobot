"""Tools for sending bounded messages between persisted sessions."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict, deque
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
from nanobot.session.session_handles import (
    SessionHandleResolver,
    normalize_session_handle,
    session_handle_for_name,
)
from nanobot.session.session_messages import (
    SESSION_MESSAGE_METADATA_KEY,
    SessionMessageEnvelope,
    session_message_envelope,
)

_RATE_LIMIT_WINDOW_SECONDS = 60.0
MIN_REPLY_TIMEOUT_SECONDS = 5
MAX_REPLY_TIMEOUT_SECONDS = 60


class SessionMessageError(ValueError):
    pass


class _CancelHandle(Protocol):
    def cancel(self) -> None: ...


@dataclass(slots=True)
class _PendingReply:
    timeout_seconds: int
    target_handle: str
    request: SessionMessageEnvelope
    timer: _CancelHandle | None = None


@tool_parameters(tool_parameters_schema())
class ListSessionsTool(Tool):
    """List the handles of other persisted sessions."""

    def __init__(self, sessions: SessionManager) -> None:
        self._handles = SessionHandleResolver(sessions)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        if ctx.sessions is None:
            raise RuntimeError("list_sessions requires a session manager")
        return cls(ctx.sessions)

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.sessions is not None

    @property
    def name(self) -> str:
        return "list_sessions"

    @property
    def description(self) -> str:
        return "List other persisted sessions by @handle."

    async def execute(self, **kwargs: Any) -> str:
        request = current_request_context()
        if request is None or not request.session_key:
            return ToolResult.error("Error: session context is unavailable")
        handles = await asyncio.to_thread(self._handles.list_all)
        return json.dumps(
            [
                f"@{handle.name}"
                for handle in handles
                if handle.session_key != request.session_key
            ],
            ensure_ascii=True,
        )


@tool_parameters(
    tool_parameters_schema(
        to=StringSchema("Target @handle."),
        content=StringSchema("Message."),
        expect_reply=BooleanSchema(description="Notify this session if no reply arrives."),
        reply_timeout_seconds=IntegerSchema(
            description="Timeout before that notification; required when expect_reply is true.",
            minimum=MIN_REPLY_TIMEOUT_SECONDS,
            maximum=MAX_REPLY_TIMEOUT_SECONDS,
        ),
        required=["to", "content", "expect_reply"],
    )
)
class SendSessionMessageTool(Tool):
    """Send text to another persisted session."""

    def __init__(
        self,
        *,
        sessions: SessionManager,
        bus: MessageBus,
        max_messages_per_minute: int = 6,
        schedule_later: Callable[[float, Callable[[], None]], _CancelHandle] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._bus = bus
        self._handles = SessionHandleResolver(sessions)
        self._max_messages_per_minute = max_messages_per_minute
        self._schedule_later = schedule_later
        self._clock = clock or time.monotonic
        self._sent_at: OrderedDict[str, deque[float]] = OrderedDict()
        self._pending_replies: dict[tuple[str, str], _PendingReply] = {}
        self._expiry_tasks: set[asyncio.Task[None]] = set()
        self._send_lock = asyncio.Lock()

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        if ctx.sessions is None or ctx.bus is None:
            raise RuntimeError("send_session_message requires sessions and a message bus")
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
        return "Send a message to a persisted session by @handle."

    def runtime_context_provider(self):
        return self._provide_runtime_context

    async def _provide_runtime_context(
        self,
        request: RequestContext,
    ) -> RuntimeContextBlock | None:
        envelope = session_message_envelope(request.metadata)
        if envelope is None:
            return None
        source = session_handle_for_name(
            envelope["source_session_key"],
            envelope["source_handle"],
        )
        content = f"Message from @{source.name}."
        if envelope["expect_reply"]:
            content += " Reply with send_session_message."
        return RuntimeContextBlock(source="session_message", content=content)

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
        if request is None or not request.session_key:
            return ToolResult.error("Error: session context is unavailable")
        try:
            target = await self.enqueue(
                source_session_key=request.session_key,
                target_handle=to,
                content=strip_think(content),
                expect_reply=expect_reply,
                reply_timeout_seconds=reply_timeout_seconds,
            )
        except SessionMessageError as exc:
            return ToolResult.error(f"Error: {exc}")
        if expect_reply:
            return (
                f"Sent to {target}. A timeout notice will arrive after "
                f"{reply_timeout_seconds}s unless it replies."
            )
        return f"Sent to {target}."

    async def enqueue(
        self,
        *,
        source_session_key: str,
        target_handle: str,
        content: str,
        expect_reply: bool,
        reply_timeout_seconds: int | None = None,
    ) -> str:
        timeout_seconds = self._validate_reply_timeout(expect_reply, reply_timeout_seconds)
        try:
            target_name = normalize_session_handle(target_handle)
        except ValueError as exc:
            raise SessionMessageError(str(exc)) from exc
        target = await asyncio.to_thread(self._handles.resolve, target_name)
        if target is None:
            raise SessionMessageError(f"session @{target_name} was not found")

        source = await asyncio.to_thread(
            self._handles.handle_for_session,
            source_session_key,
        )
        if source is None:
            raise SessionMessageError("source session was not found")
        envelope: SessionMessageEnvelope = {
            "message_id": uuid4().hex,
            "created_at_ms": int(time.time() * 1000),
            "expect_reply": expect_reply,
            "source_handle": source.name,
            "source_session_key": source.session_key,
            "target_session_key": target.session_key,
        }
        reverse_wait_key = (target.session_key, source.session_key)
        wait_key = (source.session_key, target.session_key)

        async with self._send_lock:
            now = self._clock()
            cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
            self._prune_expired_rate_limits(cutoff)
            sent_at = self._sent_at.get(source.session_key)
            if sent_at is None:
                sent_at = deque[float]()
            while sent_at and sent_at[0] <= cutoff:
                sent_at.popleft()
            if len(sent_at) >= self._max_messages_per_minute:
                raise SessionMessageError(
                    f"session message rate limit reached ({self._max_messages_per_minute}/minute)",
                )

            await self._bus.publish_inbound(InboundMessage(
                channel="system",
                sender_id="session",
                chat_id=target.session_key,
                content=content,
                metadata={SESSION_MESSAGE_METADATA_KEY: envelope},
                session_key_override=target.session_key,
                input_role="user",
            ))
            sent_at.append(now)
            self._sent_at[source.session_key] = sent_at
            self._sent_at.move_to_end(source.session_key)
            self._cancel_pending_reply(reverse_wait_key)
            if timeout_seconds is not None:
                self._cancel_pending_reply(wait_key)
                self._schedule_pending_reply(
                    wait_key,
                    timeout_seconds,
                    target.name,
                    envelope,
                )

        return f"@{target.name}"

    def _prune_expired_rate_limits(self, cutoff: float) -> None:
        """Drop sources ordered by their most recent successful send."""
        while self._sent_at:
            _, sent_at = next(iter(self._sent_at.items()))
            if sent_at[-1] > cutoff:
                return
            self._sent_at.popitem(last=False)

    @staticmethod
    def _validate_reply_timeout(
        expect_reply: bool,
        reply_timeout_seconds: int | None,
    ) -> int | None:
        if not expect_reply:
            return None
        if (
            reply_timeout_seconds is None
            or not MIN_REPLY_TIMEOUT_SECONDS
            <= reply_timeout_seconds
            <= MAX_REPLY_TIMEOUT_SECONDS
        ):
            raise SessionMessageError(
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
        timeout_seconds: int,
        target_handle: str,
        request: SessionMessageEnvelope,
    ) -> None:
        pending = _PendingReply(
            timeout_seconds=timeout_seconds,
            target_handle=target_handle,
            request=request,
        )
        self._pending_replies[key] = pending

        def expire() -> None:
            task = asyncio.create_task(self._expire_pending_reply(key, pending))
            self._expiry_tasks.add(task)
            task.add_done_callback(self._expiry_tasks.discard)

        schedule = self._schedule_later or asyncio.get_running_loop().call_later
        pending.timer = schedule(float(timeout_seconds), expire)

    async def _expire_pending_reply(
        self,
        key: tuple[str, str],
        expected: _PendingReply,
    ) -> None:
        async with self._send_lock:
            if self._pending_replies.get(key) is not expected:
                return
            self._pending_replies.pop(key, None)
            source_session_key = expected.request["source_session_key"]
            await self._bus.publish_inbound(InboundMessage(
                channel="system",
                sender_id="session_timeout",
                chat_id=source_session_key,
                content=(
                    f"No reply from @{expected.target_handle} after "
                    f"{expected.timeout_seconds} seconds."
                ),
                session_key_override=source_session_key,
                input_role="user",
            ))
