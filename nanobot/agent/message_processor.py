"""Per-message processing pipeline.

``MessageProcessor`` owns the per-message lifecycle: session lookup,
slash-command handling, memory pre-checks, context assembly, canonical
event building, turn orchestration, session save, and response assembly.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.agent_components import _ProcessorServices
from nanobot.agent.callbacks import ProgressCallback
from nanobot.agent.turn_types import TurnState
from nanobot.agent.verifier import AnswerVerifier
from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.config.schema import AgentConfig
from nanobot.observability.bus_progress import make_bus_progress
from nanobot.observability.langfuse import update_current_span
from nanobot.observability.tracing import TraceContext, bind_trace
from nanobot.session.manager import Session

if TYPE_CHECKING:
    from nanobot.coordination.coordinator import ClassificationResult
    from nanobot.coordination.role_switching import TurnRoleManager
    from nanobot.providers.base import LLMProvider


class MessageProcessor:
    """Per-message processing pipeline: InboundMessage to OutboundMessage."""

    def __init__(
        self,
        *,
        services: _ProcessorServices,
        config: AgentConfig,
        workspace: Path,
        role_name: str,
        provider: LLMProvider,
        model: str,
    ) -> None:
        self.orchestrator = services.orchestrator
        self._dispatcher = services.dispatcher
        self._missions = services.missions
        self.context = services.context
        self.sessions = services.sessions
        self.tools = services.tools
        self._consolidator = services.consolidator
        self.verifier = services.verifier
        self.bus = services.bus
        self._turn_context = services.turn_context
        self._span_module: Any | None = services.span_module
        self.config = config
        self.workspace = workspace
        self.role_name = role_name
        self._role_manager: TurnRoleManager | None = None
        self.provider = provider
        self.model = model

        # Per-turn token accumulators (populated from TurnResult).
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        # Classification result (consumed by _run_orchestrator each turn).
        self.classification_result: ClassificationResult | None = None

        # Per-turn active settings (set by AgentLoop before each turn).
        self._active_model: str | None = None
        self._active_temperature: float | None = None
        self._active_max_iterations: int | None = None
        self._active_role_name: str | None = None

        # Last TurnResult from the orchestrator, used by _sync_token_counters.
        self._last_turn_result: Any | None = None

    def set_role_manager(self, role_manager: TurnRoleManager) -> None:
        """Set the role manager (called by the factory after construction)."""
        self._role_manager = role_manager

    def set_classification_result(self, result: ClassificationResult | None) -> None:
        """Forward a coordinator classification result for the next turn."""
        self.classification_result = result

    def set_active_settings(
        self,
        *,
        model: str,
        temperature: float,
        max_iterations: int,
        role_name: str,
    ) -> None:
        """Forward role-switched settings for the upcoming turn."""
        self._active_model = model
        self._active_temperature = temperature
        self._active_max_iterations = max_iterations
        self._active_role_name = role_name

    async def process(
        self,
        message: InboundMessage,
        on_progress: ProgressCallback | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
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
        """Process a message directly (for CLI or cron usage)."""
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""

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
            self._turn_context.set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
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
        assert memory_store is not None  # always injected by build_agent

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
        if self.config.memory_enabled and unconsolidated >= self.config.memory_window:
            self._consolidator.submit(session.key, session, self.provider, self.model)

        self._turn_context.set_tool_context(
            msg.channel, msg.chat_id, msg.metadata.get("message_id")
        )
        self._turn_context.ensure_scratchpad(key, self.workspace)
        if message_tool := self.tools.get("message"):
            message_tool.on_turn_start()

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

        final_content, tools_used, all_msgs = await self._run_orchestrator(
            initial_messages,
            on_progress=(on_progress or _bus_progress) if self.config.streaming_enabled else None,
        )

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

        if msg_tool := self.tools.get("message"):
            if msg_tool.sent_in_turn:
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

    def _sync_token_counters(self) -> None:
        """Pull token counters from the last ``TurnResult``."""
        result = self._last_turn_result
        if result is None:
            return
        self._turn_tokens_prompt = getattr(result, "tokens_prompt", 0)
        self._turn_tokens_completion = getattr(result, "tokens_completion", 0)
        self._turn_llm_calls = getattr(result, "llm_calls", 0)

    async def _run_orchestrator(
        self,
        messages: list[dict[str, Any]],
        on_progress: ProgressCallback | None,
    ) -> tuple[str | None, list[str], list[dict[str, Any]]]:
        """Build TurnState, call orchestrator, unpack result to 3-tuple."""
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
            classification_result=self.classification_result,
            tools_def_cache=list(self.tools.get_definitions()),
        )
        self.classification_result = None  # consumed
        result = await self.orchestrator.run(state, on_progress)
        self._last_turn_result = result  # stored for _sync_token_counters

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

    async def _pre_turn_memory(
        self,
        msg: InboundMessage,
        memory_store: Any,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Run memory pre-checks: conflict reply and live correction."""
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

    def _save_turn(self, session: Session, messages: list[dict[str, Any]], skip: int) -> None:
        """Save new-turn messages into session, skipping ephemeral system messages."""
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

    async def _consolidate_memory(self, session: Session, archive_all: bool = False) -> bool:
        """Delegate to ConsolidationOrchestrator."""
        if archive_all:
            return await self._consolidator.consolidate_and_wait(
                session.key, session, self.provider, self.model, archive_all=True
            )
        self._consolidator.submit(session.key, session, self.provider, self.model)
        return True
