"""Message handler: processes a single inbound message via state machine.

Follows upstream nanobot's state-machine pattern for traceability,
error isolation, and testability. Keeps blackcat-specific author resolution
and button support in outbound messages.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from blackcat.agent.tools.ask import (
    ask_user_options_from_messages,
    ask_user_outbound,
    ask_user_tool_result_messages,
    pending_ask_user_id,
)
from blackcat.agent.tools.message import MessageTool
from blackcat.bus.events import OutboundMessage
from blackcat.command import CommandContext
from blackcat.config.schema import Config
from blackcat.utils.document import extract_documents
from blackcat.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

if TYPE_CHECKING:
    from blackcat.agent.loop import AgentLoop
    from blackcat.bus.events import InboundMessage


# ── State machine types ──────────────────────────────────────────────────


class TurnState(Enum):
    RESTORE = auto()
    COMPACT = auto()
    COMMAND = auto()
    BUILD = auto()
    RUN = auto()
    SAVE = auto()
    RESPOND = auto()
    DONE = auto()


@dataclass
class StateTraceEntry:
    state: TurnState
    started_at: float
    duration_ms: float
    event: str
    error: str | None = None


@dataclass
class TurnContext:
    """Per-turn state carried through the state machine."""

    msg: InboundMessage
    session_key: str
    state: TurnState
    turn_id: str

    session: Any = None
    history: list[dict[str, Any]] = field(default_factory=list)
    initial_messages: list[dict[str, Any]] = field(default_factory=list)

    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    all_messages: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    had_injections: bool = False

    user_persisted_early: bool = False
    save_skip: int = 0
    outbound: OutboundMessage | None = None
    suppress_response: bool = False

    on_progress: Callable[..., Awaitable[None]] | None = None
    on_stream: Callable[[str], Awaitable[None]] | None = None
    on_stream_end: Callable[..., Awaitable[None]] | None = None
    on_retry_wait: Callable[[str], Awaitable[None]] | None = None

    pending_queue: asyncio.Queue | None = None
    pending_summary: str | None = None

    trace: list[StateTraceEntry] = field(default_factory=list)
    turn_wall_started_at: float = field(default_factory=time.time)

    # blackcat-specific: resolved author identity for this turn
    author: str = "user"


# Event-driven state transition table.
# Handlers return an event string; the driver looks up the next state here.
_TRANSITIONS: dict[tuple[TurnState, str], TurnState] = {
    (TurnState.RESTORE, "ok"): TurnState.COMPACT,
    (TurnState.COMPACT, "ok"): TurnState.COMMAND,
    (TurnState.COMMAND, "dispatch"): TurnState.BUILD,
    (TurnState.COMMAND, "shortcut"): TurnState.DONE,
    (TurnState.BUILD, "ok"): TurnState.RUN,
    (TurnState.RUN, "ok"): TurnState.SAVE,
    (TurnState.SAVE, "ok"): TurnState.RESPOND,
    (TurnState.RESPOND, "ok"): TurnState.DONE,
}


# ── MessageHandler ───────────────────────────────────────────────────────


class MessageHandler:
    """
    Handles a single inbound message through the agent state machine.

    Delegates to AgentLoop for:
    - Session management
    - Tool execution (ToolRegistry)
    - LLM provider calls (AgentRunner)
    - Runtime checkpoint save/restore helpers
    """

    __slots__ = ("_loop", "_msg", "config")

    def __init__(self, loop: "AgentLoop", msg: "InboundMessage", config: Config) -> None:
        self._loop = loop
        self._msg = msg
        self.config = config

    async def process(
        self,
        session_key: str | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        pending_queue: Any | None = None,
    ) -> OutboundMessage | None:
        """
        Process the inbound message and return a response.

        Drives the state machine (RESTORE → COMPACT → COMMAND → BUILD →
        RUN → SAVE → RESPOND → DONE) for structured error isolation.
        """
        loop = self._loop
        msg = self._msg

        loop._refresh_provider_snapshot()

        # System messages bypass the state machine
        if msg.channel == "system":
            return await self._process_system_message(
                msg, pending_queue=pending_queue,
            )

        # Extract document text from media (PDF, DOCX, etc.) upfront
        if msg.media:
            new_content, image_only = extract_documents(msg.content, msg.media)
            msg = msg.__class__(
                channel=msg.channel,
                sender_id=msg.sender_id,
                chat_id=msg.chat_id,
                content=new_content,
                media=image_only,
                metadata=msg.metadata,
            )

        # Resolve author identity (blackcat-specific)
        author = self.config.resolve_author(msg.sender_id, msg.channel)

        key = session_key or msg.session_key
        ctx = TurnContext(
            msg=msg,
            session_key=key,
            state=TurnState.RESTORE,
            turn_id=f"{key}:{time.time_ns()}",
            turn_wall_started_at=time.time(),
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            pending_queue=pending_queue,
            author=author,
        )

        while ctx.state is not TurnState.DONE:
            handler_name = f"_state_{ctx.state.name.lower()}"
            handler = getattr(self, handler_name, None)
            if handler is None:
                raise RuntimeError(f"Missing state handler for {ctx.state}")

            t0 = time.perf_counter()
            try:
                event = await handler(ctx)
            except Exception:
                duration = (time.perf_counter() - t0) * 1000
                ctx.trace.append(
                    StateTraceEntry(
                        state=ctx.state,
                        started_at=t0,
                        duration_ms=duration,
                        event="",
                        error="exception",
                    )
                )
                raise

            duration = (time.perf_counter() - t0) * 1000
            ctx.trace.append(
                StateTraceEntry(
                    state=ctx.state,
                    started_at=t0,
                    duration_ms=duration,
                    event=event,
                )
            )
            logger.debug(
                "[turn {}] State {} took {:.1f}ms -> event {}",
                ctx.turn_id,
                ctx.state.name,
                duration,
                event,
            )

            next_state = _TRANSITIONS.get((ctx.state, event))
            if next_state is None:
                raise RuntimeError(
                    f"[turn {ctx.turn_id}] No transition from {ctx.state} "
                    f"on event {event!r}"
                )
            ctx.state = next_state

        logger.debug(
            "[turn {}] Turn completed after {} states",
            ctx.turn_id,
            len(ctx.trace),
        )
        return ctx.outbound

    # ── State handlers ───────────────────────────────────────────────────

    async def _state_restore(self, ctx: TurnContext) -> str:
        """Restore checkpoint / pending user turn."""
        loop = self._loop
        msg = ctx.msg

        # Session management
        session = loop.sessions.get_or_create(ctx.session_key)
        if loop._restore_runtime_checkpoint(session):
            loop.sessions.save(session)
        if loop._restore_pending_user_turn(session):
            loop.sessions.save(session)
        ctx.session = session
        return "ok"

    async def _state_compact(self, ctx: TurnContext) -> str:
        """Auto-compact session if idle; run consolidation."""
        loop = self._loop
        session, pending = loop.auto_compact.prepare_session(ctx.session, ctx.session_key)
        ctx.session = session
        ctx.pending_summary = pending
        return "ok"

    async def _state_command(self, ctx: TurnContext) -> str:
        """Dispatch slash commands if applicable."""
        loop = self._loop
        msg = ctx.msg
        raw = msg.content.strip()
        cmd_ctx = CommandContext(
            msg=msg, session=ctx.session, key=ctx.session_key,
            raw=raw, loop=loop,
        )
        if result := await loop.commands.dispatch(cmd_ctx):
            ctx.outbound = result
            # Persist user message for commands other than /new
            if raw.lower() != "/new":
                ctx.user_persisted_early = True
                extra: dict[str, Any] = {}
                ctx.session.add_message("user", raw, **extra)
                loop._mark_pending_user_turn(ctx.session)
                ctx.session.add_message("assistant", result.content, _command=True)
                loop.sessions.save(ctx.session)
                loop._clear_pending_user_turn(ctx.session)
            return "shortcut"
        return "dispatch"

    async def _state_build(self, ctx: TurnContext) -> str:
        """Build context, history, and initial messages for the LLM."""
        loop = self._loop
        msg = ctx.msg

        # Token-budget consolidation
        await loop.consolidator.maybe_consolidate_by_tokens(
            ctx.session, session_summary=ctx.pending_summary,
        )

        # Set tool context for this turn
        loop._set_tool_context(
            msg.channel, msg.chat_id, msg.metadata.get("message_id"),
        )

        # Reset per-turn MessageTool tracking
        message_tool = loop.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.start_turn()

        # Build history
        ctx.history = ctx.session.get_history(
            max_messages=loop._max_messages, include_timestamps=True,
        )

        # Handle pending ask_user response
        pending_ask_id = pending_ask_user_id(ctx.history)
        if pending_ask_id:
            system_prompt = await loop.context.build_system_prompt(
                author=ctx.author,
                channel=msg.channel,
            )
            ctx.initial_messages = ask_user_tool_result_messages(
                system_prompt,
                ctx.history,
                pending_ask_id,
                msg.content,
            )
        else:
            ctx.initial_messages = await loop.context.build_messages(
                history=ctx.history,
                current_message=msg.content,
                media=msg.media if msg.media else None,
                channel=msg.channel,
                chat_id=loop._runtime_chat_id(msg),
                author=ctx.author,
            )

        # Build progress callbacks (lazy — only if not provided externally)
        if ctx.on_progress is None:
            ctx.on_progress = await self._build_bus_progress_callback(msg, loop)
        if ctx.on_retry_wait is None:
            ctx.on_retry_wait = await self._build_retry_wait_callback(msg, loop)

        # Persist the triggering user message up front so a mid-turn crash
        # doesn't silently lose the prompt on recovery.
        ctx.user_persisted_early = self._persist_user_message_early(ctx)

        return "ok"

    async def _state_run(self, ctx: TurnContext) -> str:
        """Execute the agent loop with the built context."""
        loop = self._loop
        msg = ctx.msg

        result = await loop._run_agent_loop(
            ctx.initial_messages,
            on_progress=ctx.on_progress,
            on_stream=ctx.on_stream,
            on_stream_end=ctx.on_stream_end,
            on_retry_wait=ctx.on_retry_wait,
            session=ctx.session,
            channel=msg.channel,
            chat_id=msg.chat_id,
            message_id=msg.metadata.get("message_id"),
            metadata=msg.metadata,
            pending_queue=ctx.pending_queue,
        )
        final_content, tools_used, all_msgs, stop_reason, had_injections = result
        ctx.final_content = final_content
        ctx.tools_used = tools_used
        ctx.all_messages = all_msgs
        ctx.stop_reason = stop_reason
        ctx.had_injections = had_injections
        return "ok"

    async def _state_save(self, ctx: TurnContext) -> str:
        """Persist turn results and clean up session state."""
        loop = self._loop

        if ctx.final_content is None or not ctx.final_content.strip():
            ctx.final_content = EMPTY_FINAL_RESPONSE_MESSAGE

        # Compute save_skip: existing history length + early-persisted user msg
        ctx.save_skip = 1 + len(ctx.history) + (1 if ctx.user_persisted_early else 0)

        loop._save_turn(ctx.session, ctx.all_messages, ctx.save_skip)
        loop._clear_pending_user_turn(ctx.session)
        loop._clear_runtime_checkpoint(ctx.session)
        loop.sessions.save(ctx.session)
        loop._schedule_background(
            loop.consolidator.maybe_consolidate_by_tokens(ctx.session),
        )
        return "ok"

    async def _state_respond(self, ctx: TurnContext) -> str:
        """Assemble the outbound response message."""
        loop = self._loop
        msg = ctx.msg

        if ctx.suppress_response:
            ctx.outbound = None
            return "ok"

        stop_reason = ctx.stop_reason

        # Suppress response if MessageTool already sent to this target
        if (
            (mt := loop.tools.get("message"))
            and isinstance(mt, MessageTool)
            and mt._sent_in_turn
        ):
            if not ctx.had_injections or stop_reason == "empty_final_response":
                ctx.outbound = None
                return "ok"

        preview = (
            ctx.final_content[:120] + "..."
            if len(ctx.final_content) > 120
            else ctx.final_content
        )
        logger.info(
            "Response to {}:{}: {}", msg.channel, msg.sender_id, preview,
        )

        meta = dict(msg.metadata or {})
        options = (
            ask_user_options_from_messages(ctx.all_messages)
            if stop_reason == "ask_user"
            else []
        )
        content, buttons = ask_user_outbound(
            ctx.final_content,
            options,
            msg.channel,
        )
        if ctx.on_stream is not None and stop_reason not in {"ask_user", "error"}:
            meta["_streamed"] = True

        ctx.outbound = OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=content,
            metadata=meta,
            buttons=buttons,
        )
        return "ok"

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _build_bus_progress_callback(
        self,
        msg: "InboundMessage",
        loop: "AgentLoop",
    ) -> Callable[..., Awaitable[None]]:
        """Build a progress callback that publishes to the message bus."""

        async def _bus_progress(
            content: str,
            *,
            tool_hint: bool = False,
            tool_events: list[dict[str, Any]] | None = None,
        ) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            if tool_events:
                meta["_tool_events"] = tool_events
            await loop.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        return _bus_progress

    async def _build_retry_wait_callback(
        self,
        msg: "InboundMessage",
        loop: "AgentLoop",
    ) -> Callable[[str], Awaitable[None]]:
        """Build a retry-wait callback that publishes to the message bus."""

        async def _on_retry_wait(content: str) -> None:
            meta = dict(msg.metadata or {})
            meta["_retry_wait"] = True
            await loop.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        return _on_retry_wait

    def _persist_user_message_early(self, ctx: TurnContext) -> bool:
        """Persist the user message early for crash recovery."""
        loop = self._loop
        msg = ctx.msg

        media_paths = [
            p for p in (msg.media or []) if isinstance(p, str) and p
        ]
        has_text = isinstance(msg.content, str) and msg.content.strip()

        # Don't double-persist if there's a pending ask_user
        if pending_ask_user_id(ctx.history):
            return False

        if not has_text and not media_paths:
            return False

        extra: dict[str, Any] = {"media": list(media_paths)} if media_paths else {}
        text = msg.content if isinstance(msg.content, str) else ""
        ctx.session.add_message("user", text, **extra)
        loop._mark_pending_user_turn(ctx.session)
        loop.sessions.save(ctx.session)
        return True

    # ── System message handling ──────────────────────────────────────────

    async def _process_system_message(
        self,
        msg: "InboundMessage",
        pending_queue: Any | None = None,
    ) -> OutboundMessage | None:
        """Process system message (subagent follow-up, background task)."""
        loop = self._loop

        # Parse origin from chat_id ("channel:chat_id")
        channel, chat_id = (
            msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
        )
        logger.info("Processing system message from {}", msg.sender_id)

        # Use session_key_override if provided (for thread-scoped sessions)
        key = getattr(msg, "session_key_override", None) or f"{channel}:{chat_id}"
        session = loop.sessions.get_or_create(key)

        # Restore checkpoint state from crash recovery
        if loop._restore_runtime_checkpoint(session):
            loop.sessions.save(session)
        if loop._restore_pending_user_turn(session):
            loop.sessions.save(session)

        # Prepare session (auto-compact if idle)
        session, pending = loop.auto_compact.prepare_session(session, key)

        # Token-budget consolidation
        await loop.consolidator.maybe_consolidate_by_tokens(session)

        # Persist subagent follow-ups before prompt assembly
        is_subagent = msg.sender_id == "subagent"
        if is_subagent and loop._persist_subagent_followup(session, msg):
            loop.sessions.save(session)

        # Set tool context for this turn
        loop._set_tool_context(
            channel, chat_id, msg.metadata.get("message_id"),
            metadata=msg.metadata.get("channel_meta"),
            session_key=getattr(msg, "session_key_override", None),
        )

        history = session.get_history(
            max_messages=loop._max_messages, include_timestamps=True,
        )

        # Subagent content is already in `history`; passing it again would
        # double-project. System messages use "system" as author.
        messages = await loop.context.build_messages(
            history=history,
            current_message="" if is_subagent else msg.content,
            channel=channel,
            chat_id=chat_id,
            author="system",
        )

        final_content, _, all_msgs, stop_reason, _ = await loop._run_agent_loop(
            messages,
            session=session,
            channel=channel,
            chat_id=chat_id,
            message_id=msg.metadata.get("message_id"),
            pending_queue=pending_queue,
        )

        loop._save_turn(session, all_msgs, 1 + len(history))
        loop._clear_runtime_checkpoint(session)
        loop.sessions.save(session)
        loop._schedule_background(
            loop.consolidator.maybe_consolidate_by_tokens(session),
        )

        # Restore channel metadata from session context for outbound routing
        # (e.g., Slack thread_ts from session_key like "slack:C123:1700.42")
        outbound_meta: dict = {}
        session_key = (
            getattr(msg, "session_key_override", None) or f"{channel}:{chat_id}"
        )
        if channel == "slack" and ":" in session_key:
            parts = session_key.split(":")
            if len(parts) >= 3:
                outbound_meta["slack"] = {"thread_ts": parts[2]}

        options = (
            ask_user_options_from_messages(all_msgs)
            if stop_reason == "ask_user"
            else []
        )
        content, buttons = ask_user_outbound(
            final_content or "Background task completed.",
            options,
            channel,
        )
        return OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            metadata=outbound_meta,
            buttons=buttons,
        )