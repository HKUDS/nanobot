"""Per-message processing pipeline.

``MessageProcessor`` owns the per-message lifecycle: session lookup,
slash-command handling, memory pre-checks, context assembly, canonical
event building, progress callback wiring, turn orchestration, session
save, and response assembly.

Extracted from ``AgentLoop._process_message`` (Task 3 of the loop
decomposition).  See ``docs/superpowers/specs/2026-03-22-loop-decomposition-design.md``,
Section 4.

Module boundary: this module must **never** import from ``nanobot.channels.*``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from nanobot.agent.bus_progress import make_bus_progress
from nanobot.agent.callbacks import ProgressCallback
from nanobot.agent.consolidation import ConsolidationOrchestrator
from nanobot.agent.context import ContextBuilder
from nanobot.agent.observability import update_current_span
from nanobot.agent.role_switching import TurnRoleManager
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.scratchpad import ScratchpadReadTool, ScratchpadWriteTool
from nanobot.agent.tracing import TraceContext, bind_trace
from nanobot.agent.verifier import AnswerVerifier
from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.scratchpad import Scratchpad
    from nanobot.agent.tool_executor import ToolExecutor
    from nanobot.providers.base import LLMProvider


class MessageProcessor:
    """Per-message processing pipeline.

    Owns everything between receiving an ``InboundMessage`` and emitting an
    ``OutboundMessage``: session lookup, slash-command handling, memory
    pre-checks, context assembly, canonical events, turn orchestration
    (via the injected orchestrator), session save, and response assembly.

    Consolidation is triggered per-message via the injected
    ``ConsolidationOrchestrator`` (submit / consolidate_and_wait).
    """

    def __init__(
        self,
        *,
        orchestrator: Any,
        context: ContextBuilder | Any,
        sessions: SessionManager | Any,
        tools: ToolExecutor | Any,
        consolidator: ConsolidationOrchestrator | Any,
        verifier: AnswerVerifier | Any,
        bus: MessageBus | Any,
        config: AgentConfig | Any,
        workspace: Path,
        role_name: str,
        role_manager: TurnRoleManager | Any,
        provider: LLMProvider | Any,
        model: str,
    ) -> None:
        self.orchestrator = orchestrator
        self.context = context
        self.sessions = sessions
        self.tools = tools
        self._consolidator = consolidator
        self.verifier = verifier
        self.bus = bus
        self.config = config
        self.workspace = workspace
        self.role_name = role_name
        self._role_manager = role_manager
        self.provider = provider
        self.model = model

        # Per-turn token accumulators: these are read by the pipeline when
        # building the response metadata.  The actual values are updated by
        # TurnOrchestrator during the turn.  When a token source is wired via
        # _token_source (set by AgentLoop after construction), that source's
        # counters are used instead.  When no source is wired, we fall back to
        # local zeros.
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0
        self._token_source: Any | None = None  # Set by AgentLoop for shared counters

        # Observability hook: reference to the module whose
        # ``update_current_span`` should be called.  AgentLoop sets this
        # to the ``nanobot.agent.loop`` module so that tests patching
        # ``nanobot.agent.loop.update_current_span`` see their patches
        # take effect at call time (the attribute is resolved late).
        self._span_module: Any | None = None

        # Contacts provider callback (forwarded from AgentLoop.set_contacts_provider)
        self._contacts_provider: Callable[[], list[str]] | None = None

        # Scratchpad reference (set lazily via _ensure_scratchpad)
        self._scratchpad: Scratchpad | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(
        self,
        message: InboundMessage,
        on_progress: ProgressCallback | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response.

        This is the main entry point, equivalent to the former
        ``AgentLoop._process_message``.
        """
        return await self._process_message(message, on_progress=on_progress)

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: ProgressCallback | None = None,
        forced_role: str | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage).

        This is the main direct-invocation entry point, equivalent to
        the former ``AgentLoop.process_direct``.

        Builds an ``InboundMessage`` and delegates to ``_process_message()``,
        passing the explicit ``session_key`` so callers can override the
        default ``channel:chat_id`` key.

        Note: ``forced_role`` is accepted for API compatibility but is a
        no-op at this layer.  Role switching based on ``forced_role`` is
        resolved by the ``AgentLoop`` before calling into the processor.
        """
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        t0_request = time.monotonic()

        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.config.memory_window)
            skill_names = self.context.skills.detect_relevant_skills(msg.content)
            messages = await self.context.build_messages(
                history=history,
                current_message=msg.content,
                skill_names=skill_names,
                channel=channel,
                chat_id=chat_id,
            )
            final_content, tools_used, all_msgs = await self._run_orchestrator(
                messages, on_progress
            )
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
            )

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        bind_trace().info(
            "Processing message from {}:{}: {}",
            msg.channel,
            msg.sender_id,
            preview,
        )

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            return await self._handle_slash_new(msg, session)
        if cmd == "/help":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "\U0001f408 nanobot commands:\n"
                    "/new \u2014 Start a new conversation\n"
                    "/help \u2014 Show available commands"
                ),
            )

        memory_store = self.context.memory

        # Run memory pre-checks (conflict resolution and live corrections).
        # These are only meaningful when the memory subsystem is wired up;
        # skip when memory is disabled to avoid exercising stub/mock stores.
        pending_conflict_question: str | None = None
        if self.config.memory_enabled:
            conflict_reply, correction_result = await self._pre_turn_memory(msg, memory_store)
            if conflict_reply.get("handled"):
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=str(conflict_reply.get("message", "")),
                )

            if correction_result and correction_result.get("question"):
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=str(correction_result.get("question", "")),
                )

            # Defer conflict questions until after the agent answers
            pending_conflict_question = memory_store.conflict_mgr.ask_user_for_conflict(
                user_message=msg.content,
            )

        # Trigger background consolidation if needed
        unconsolidated = len(session.messages) - session.last_consolidated
        if (
            self.config.memory_enabled
            and unconsolidated >= self.config.memory_window
        ):
            self._consolidator.submit(session.key, session, self.provider, self.model)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        self._ensure_scratchpad(key)
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=self.config.memory_window)
        verify_before_answer = self.verifier.should_force_verification(msg.content)
        skill_names = self.context.skills.detect_relevant_skills(msg.content)
        initial_messages = await self.context.build_messages(
            history=history,
            current_message=msg.content,
            skill_names=skill_names,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            verify_before_answer=verify_before_answer,
        )

        # Build canonical event builder scoped to this request
        _turn_num = len(session.messages) // 2
        _canonical_message_id = "msg_asst_" + uuid.uuid4().hex[:12]
        _canonical_builder = CanonicalEventBuilder(
            run_id=TraceContext.get()["request_id"] or key,
            session_id=key,
            turn_id=f"turn_{_turn_num:05d}",
            actor_id=self.role_name,
        )

        # Build base metadata dict once for this turn
        _base_meta: dict[str, Any] = dict(msg.metadata or {})
        _base_meta["_progress"] = True

        _bus_progress = make_bus_progress(
            bus=self.bus,
            channel=msg.channel,
            chat_id=msg.chat_id,
            base_meta=_base_meta,
            canonical_builder=_canonical_builder,
        )

        # Emit run.start + message.start before the agent loop begins
        for _start_event in (
            _canonical_builder.run_start(),
            _canonical_builder.message_start(_canonical_message_id),
        ):
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="",
                    metadata={"_progress": True, "_canonical": _start_event},
                )
            )

        # Wire the per-turn progress callback into the delegation dispatcher
        if hasattr(self.orchestrator, "_dispatcher"):
            self.orchestrator._dispatcher.on_progress = _bus_progress

        final_content, tools_used, all_msgs = await self._run_orchestrator(
            initial_messages,
            on_progress=(on_progress or _bus_progress) if self.config.streaming_enabled else None,
        )

        # Clear per-turn callback to prevent cross-turn leakage
        if hasattr(self.orchestrator, "_dispatcher"):
            self.orchestrator._dispatcher.on_progress = None

        if final_content is None:
            _recovered = await self.verifier.attempt_recovery(
                channel=msg.channel,
                chat_id=msg.chat_id,
                all_msgs=all_msgs,
            )
            if isinstance(_recovered, str):
                final_content = _recovered

        if final_content is None:
            # Ensure all_msgs is a real list for build_no_answer_explanation.
            _safe_msgs: list[dict[str, Any]] = all_msgs if isinstance(all_msgs, list) else []
            final_content = AnswerVerifier.build_no_answer_explanation(msg.content, _safe_msgs)
            _added = self.context.add_assistant_message(_safe_msgs, final_content)
            if isinstance(_added, list):
                all_msgs = _added

        # Ensure final_content is a real string for downstream consumers.
        if not isinstance(final_content, str):
            final_content = str(final_content) if final_content else ""

        # Sync token counters from the loop (where _run_agent_loop updates them)
        self._sync_token_counters()

        # Annotate the active langfuse span with request metadata + output.
        # Resolve update_current_span via _span_module (late binding) so that
        # tests patching nanobot.agent.loop.update_current_span take effect.
        _update_span = (
            getattr(self._span_module, "update_current_span", update_current_span)
            if self._span_module is not None
            else update_current_span
        )
        _update_span(
            output=final_content[:500] if final_content else None,
            metadata={
                "channel": msg.channel,
                "sender": msg.sender_id,
                "model": self.model,
                "role": self.role_name,
                "session_key": key,
                "llm_calls": str(self._turn_llm_calls),
            },
        )

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        # Request audit line
        duration_ms = (time.monotonic() - t0_request) * 1000
        bind_trace().info(
            "request_complete | {ch}:{cid} | {dur:.0f}ms | model={mdl} | tools={tc} | len={rlen}"
            " | llm_calls={lc} | prompt_tokens={pt} | completion_tokens={ct}",
            ch=msg.channel,
            cid=msg.chat_id,
            dur=duration_ms,
            mdl=self.model,
            tc=len(tools_used),
            rlen=len(final_content),
            lc=self._turn_llm_calls,
            pt=self._turn_tokens_prompt,
            ct=self._turn_tokens_completion,
        )

        if isinstance(all_msgs, list):
            self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

        # Append deferred conflict question after answering
        if pending_conflict_question:
            final_content += "\n\n---\n" + pending_conflict_question

        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                return None

        response_meta = dict(msg.metadata or {})
        response_meta["usage"] = {
            "prompt_tokens": self._turn_tokens_prompt,
            "completion_tokens": self._turn_tokens_completion,
        }
        response_meta["_canonical"] = _canonical_builder.message_end(
            _canonical_message_id,
            input_tokens=self._turn_tokens_prompt,
            output_tokens=self._turn_tokens_completion,
        )
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=response_meta,
        )

    # ------------------------------------------------------------------
    # Token counter sync
    # ------------------------------------------------------------------

    def _sync_token_counters(self) -> None:
        """Pull token counters from the orchestrator or legacy token source.

        ``TurnOrchestrator.run()`` updates ``_turn_tokens_*`` during the turn.
        Since the processor reads these counters for response metadata and
        audit logging, we sync them here.  When no source is wired (e.g. in
        unit tests with mock orchestrators), the local zeros are used.

        Also pushes the values back to ``_token_source`` (AgentLoop) so that
        tests reading ``loop._turn_tokens_prompt`` see the updated values.
        """
        # Prefer the orchestrator's counters directly
        orch = self.orchestrator
        if hasattr(orch, "_turn_tokens_prompt"):
            self._turn_tokens_prompt = getattr(orch, "_turn_tokens_prompt", 0)
            self._turn_tokens_completion = getattr(orch, "_turn_tokens_completion", 0)
            self._turn_llm_calls = getattr(orch, "_turn_llm_calls", 0)
        else:
            # Fallback: legacy _token_source (e.g. AgentLoop reference)
            src = self._token_source
            if src is not None:
                self._turn_tokens_prompt = getattr(src, "_turn_tokens_prompt", 0)
                self._turn_tokens_completion = getattr(src, "_turn_tokens_completion", 0)
                self._turn_llm_calls = getattr(src, "_turn_llm_calls", 0)

        # Push back to AgentLoop for backward-compat with tests that read
        # loop._turn_tokens_prompt directly.
        src = self._token_source
        if src is not None:
            try:
                src._turn_tokens_prompt = self._turn_tokens_prompt
                src._turn_tokens_completion = self._turn_tokens_completion
                src._turn_llm_calls = self._turn_llm_calls
            except AttributeError:
                pass  # _token_source may not expose these attrs (e.g., during testing with mocks)

    # ------------------------------------------------------------------
    # Orchestrator interaction
    # ------------------------------------------------------------------

    async def _run_orchestrator(
        self,
        messages: list[dict[str, Any]],
        on_progress: ProgressCallback | None,
    ) -> tuple[str | None, list[str], list[dict[str, Any]]]:
        """Call the orchestrator and normalise the result.

        Wraps the ``messages`` list in a ``TurnState`` for
        ``TurnOrchestrator.run()`` and unpacks the returned ``TurnResult``
        into the 3-tuple ``(content, tools_used, messages)`` expected by
        the rest of the pipeline.  Also supports mock orchestrators that
        return tuples or duck-typed result objects.
        """
        from nanobot.agent.turn_orchestrator import TurnOrchestrator, TurnState

        if isinstance(self.orchestrator, TurnOrchestrator):
            # Extract user text from the last user message (matches _run_agent_loop)
            user_text = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    _content = m.get("content", "")
                    if isinstance(_content, str):
                        user_text = _content
                    elif isinstance(_content, list):
                        user_text = " ".join(
                            p.get("text", "")
                            for p in _content
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    break
            state = TurnState(
                messages=messages,
                user_text=user_text,
                tools_def_cache=list(self.tools.get_definitions()),
            )
            # Forward classification result for plan-phase delegation advice
            if hasattr(self, "_last_classification_result"):
                self.orchestrator._last_classification_result = (
                    self._last_classification_result  # type: ignore[attr-defined]
                )
            result = await self.orchestrator.run(state, on_progress)
        else:
            result = await self.orchestrator.run(messages, on_progress)

        if isinstance(result, tuple):
            return result  # type: ignore[return-value]
        # Forward-compat for TurnResult or mock objects.
        # Use explicit str/list checks to avoid propagating MagicMock values.
        # Convert empty string content to None so the recovery path triggers.
        _content = getattr(result, "content", None)
        content: str | None = (_content or None) if isinstance(_content, str) else None
        _tools = getattr(result, "tools_used", [])
        tools_used: list[str] = _tools if isinstance(_tools, list) else []
        _msgs = getattr(result, "messages", None)
        all_msgs: list[dict[str, Any]] = _msgs if isinstance(_msgs, list) else messages
        return content, tools_used, all_msgs

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    async def _handle_slash_new(self, msg: InboundMessage, session: Session) -> OutboundMessage:
        """Handle the /new slash command: archive and clear the session."""
        try:
            snapshot = session.messages[session.last_consolidated :]
            if snapshot:
                temp = Session(key=session.key)
                temp.messages = list(snapshot)
                archived = await self._consolidate_memory(temp, archive_all=True)
                if not archived:
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Memory archival failed, session not cleared. Please try again.",
                    )
        except (RuntimeError, asyncio.TimeoutError):
            logger.exception("/new archival failed for {}", session.key)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Memory archival failed, session not cleared. Please try again.",
            )

        session.clear()
        self.sessions.save(session)
        self.sessions.invalidate(session.key)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content="New session started."
        )

    # ------------------------------------------------------------------
    # Memory pre-checks
    # ------------------------------------------------------------------

    async def _pre_turn_memory(
        self,
        msg: InboundMessage,
        memory_store: Any,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Run memory pre-checks: conflict reply and live correction.

        Runs in a thread to avoid blocking the event loop for what are
        in-memory operations.
        """
        _channel = msg.channel
        _chat_id = msg.chat_id
        _content = msg.content
        _enable_cc = self.config.memory_enable_contradiction_check

        def _inner() -> tuple[dict[str, Any], dict[str, Any] | None]:
            cr = memory_store.conflict_mgr.handle_user_conflict_reply(_content)
            if cr.get("handled"):
                return cr, None
            try:
                corr = memory_store.profile_mgr.apply_live_user_correction(
                    _content,
                    channel=_channel,
                    chat_id=_chat_id,
                    enable_contradiction_check=_enable_cc,
                )
            except (RuntimeError, KeyError, TypeError):
                logger.exception("Live correction capture failed")
                corr = {}
            return cr, corr

        return await asyncio.to_thread(_inner)

    # ------------------------------------------------------------------
    # Tool context and scratchpad
    # ------------------------------------------------------------------

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for tools that need routing info.

        Delegates to the tool executor's get() method to find typed tool
        instances and set their per-turn context.
        """
        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.feedback import FeedbackTool
        from nanobot.agent.tools.mission import MissionStartTool

        if self._contacts_provider is not None:
            self.context.set_contacts_context(self._contacts_provider())

        msg_t = self.tools.get("message")
        if isinstance(msg_t, MessageTool):
            msg_t.set_context(channel, chat_id, message_id)
        ms_t = self.tools.get("mission_start")
        if isinstance(ms_t, MissionStartTool):
            ms_t.set_context(channel, chat_id)
        cr_t = self.tools.get("cron")
        if isinstance(cr_t, CronTool):
            cr_t.set_context(channel, chat_id)
        fb_t = self.tools.get("feedback")
        if isinstance(fb_t, FeedbackTool):
            fb_t.set_context(channel, chat_id, session_key=f"{channel}:{chat_id}")

    def _ensure_scratchpad(self, session_key: str) -> None:
        """Initialise (or swap) the per-session scratchpad and update tools."""
        from nanobot.agent.scratchpad import Scratchpad
        from nanobot.utils.helpers import safe_filename

        safe_key = safe_filename(session_key.replace(":", "_"))
        session_dir = self.workspace / "sessions" / safe_key
        session_dir.mkdir(parents=True, exist_ok=True)
        self._scratchpad = Scratchpad(session_dir)

        # Update scratchpad in delegation dispatcher if accessible
        if hasattr(self.orchestrator, "_dispatcher"):
            self.orchestrator._dispatcher.scratchpad = self._scratchpad
            self.orchestrator._dispatcher._trace_path = session_dir / "routing_trace.jsonl"

        # Update scratchpad tool references
        write_tool = self.tools.get("write_scratchpad")
        if isinstance(write_tool, ScratchpadWriteTool):
            write_tool._scratchpad = self._scratchpad
        read_tool = self.tools.get("read_scratchpad")
        if isinstance(read_tool, ScratchpadReadTool):
            read_tool._scratchpad = self._scratchpad

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _save_turn(self, session: Session, messages: list[dict[str, Any]], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results.

        Ephemeral system messages (reflect, progress, self-check, delegation
        nudges) injected during the tool loop are **not** persisted — they are
        loop-control signals that would pollute conversation history and cause
        the LLM to infer false workflow patterns on future turns.
        """
        max_chars = self.config.tool_result_max_chars
        for m in messages[skip:]:
            if m.get("role") == "system":
                continue  # ephemeral loop-control prompt — do not persist
            entry = {k: v for k, v in m.items() if k != "reasoning_content"}
            if entry.get("role") == "tool" and isinstance(entry.get("content"), str):
                content = entry["content"]
                if len(content) > max_chars:
                    entry["content"] = content[:max_chars] + "\n... (truncated)"
            entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Consolidation
    # ------------------------------------------------------------------

    async def _consolidate_memory(self, session: Session, archive_all: bool = False) -> bool:
        """Delegate to ConsolidationOrchestrator."""
        if archive_all:
            return await self._consolidator.consolidate_and_wait(
                session.key, session, self.provider, self.model, archive_all=True
            )
        self._consolidator.submit(session.key, session, self.provider, self.model)
        return True
