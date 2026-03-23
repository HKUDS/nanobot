"""Agent loop: the core processing engine.

This module implements the **Plan-Act-Observe-Reflect** cycle that drives
every conversation turn:

1. **Plan** — when ``planning_enabled`` is set, the LLM produces a numbered
   plan of steps before tool execution begins.
2. **Act** — the LLM selects and calls tools via the function-calling API;
   readonly tools run in parallel, write tools run sequentially.
3. **Observe** — tool results are appended to the message history for the
   LLM to interpret.
4. **Reflect** — on tool failure or stalled progress, a reflection prompt
   asks the LLM to propose alternative strategies.

The loop enforces ``max_iterations`` to prevent runaway tool-calling and
performs context compression (via ``context.py``) when the token budget
is exceeded.  An optional self-critique verification pass gates final
response quality before delivery.

Streaming is supported: LLM tokens are yielded incrementally to the
channel for progressive display on platforms that support message editing.

**Failure classification and turn-scoped tool suppression** — see
``nanobot.agent.failure`` for ``ToolCallTracker``, ``FailureClass``, and
``_build_failure_prompt``.  Permanently failing tools and tools that hit the
``REMOVE_THRESHOLD`` count are added to a per-turn ``disabled_tools: set[str]``
local to ``_run_agent_loop``.  The ``ToolRegistry`` is never mutated; suppressed
tools are available again in the next turn.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.bus_progress import make_bus_progress
from nanobot.agent.callbacks import ProgressCallback
from nanobot.agent.capability import CapabilityRegistry
from nanobot.agent.consolidation import ConsolidationOrchestrator
from nanobot.agent.context import ContextBuilder
from nanobot.agent.delegation import DelegationConfig, DelegationDispatcher
from nanobot.agent.memory import MemoryStore
from nanobot.agent.message_processor import MessageProcessor
from nanobot.agent.mission import MissionManager
from nanobot.agent.observability import (
    flush as flush_langfuse,
)
from nanobot.agent.observability import (
    reset_trace_context,
    trace_request,
    update_current_span,
)
from nanobot.agent.prompt_loader import prompts
from nanobot.agent.reaction import classify_reaction
from nanobot.agent.role_switching import TurnContext, TurnRoleManager
from nanobot.agent.scratchpad import Scratchpad
from nanobot.agent.streaming import StreamingLLMCaller
from nanobot.agent.tool_executor import ToolExecutor
from nanobot.agent.tool_setup import register_default_tools
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.email import CheckEmailTool
from nanobot.agent.tools.feedback import FeedbackTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.mission import MissionStartTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.result_cache import ToolResultCache
from nanobot.agent.tools.scratchpad import ScratchpadReadTool, ScratchpadWriteTool
from nanobot.agent.tracing import TraceContext
from nanobot.agent.turn_orchestrator import TurnOrchestrator, TurnState
from nanobot.agent.turn_orchestrator import TurnResult as TurnResult  # noqa: F401 — re-export
from nanobot.agent.verifier import AnswerVerifier
from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.bus.events import DeliveryResult, InboundMessage, OutboundMessage, ReactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig, AgentRoleConfig, ExecToolConfig
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.coordinator import ClassificationResult, Coordinator
    from nanobot.config.schema import ChannelsConfig, RoutingConfig
    from nanobot.cron.service import CronService


# Per-coroutine delegation ancestry — canonical definition in delegation.py,
# re-exported here for backward compatibility with tests.
# Backward-compat re-exports: these symbols moved to turn_orchestrator.py or
# their original modules.  Tests that import them from loop.py still work.
from nanobot.agent.context import summarize_and_compress as summarize_and_compress  # noqa: F401
from nanobot.agent.delegation import _delegation_ancestry  # noqa: F401
from nanobot.agent.failure import FailureClass as FailureClass  # noqa: F401
from nanobot.agent.failure import ToolCallTracker as ToolCallTracker  # noqa: F401
from nanobot.agent.failure import _build_failure_prompt as _build_failure_prompt  # noqa: F401
from nanobot.agent.turn_orchestrator import (  # noqa: F401
    _dynamic_preserve_recent as _dynamic_preserve_recent,
)
from nanobot.agent.turn_orchestrator import (
    _needs_planning as _needs_planning,
)

_DEFAULT_CONFIDENCE_THRESHOLD: float = (
    0.6  # Fallback routing confidence threshold (no RoutingConfig)
)


def _user_friendly_error(exc: Exception) -> str:
    """Map exceptions to actionable user-facing messages."""
    msg = str(exc).lower()
    if "context_length" in msg or "context window" in msg or "maximum context" in msg:
        return "Your conversation is too long. Use /new to start a fresh session."
    if "rate_limit" in msg or "429" in msg or "quota" in msg:
        return "I'm rate-limited right now. Please try again in a moment."
    if "auth" in msg and ("invalid" in msg or "denied" in msg or "missing" in msg):
        return "There's a configuration issue with the AI provider. Please contact the admin."
    return "Sorry, I couldn't process that. Please try again."


class AgentLoop:
    """Core processing engine for the nanobot agent.

    Orchestrates the Plan-Act-Observe-Reflect cycle for every conversation turn.
    Key collaborators wired in ``__init__``:

    - ``ToolExecutor`` / ``ToolRegistry`` — parallel-safe tool batching
    - ``CapabilityRegistry`` — unified registry for tools, skills, and delegate roles
    - ``DelegationDispatcher`` — multi-agent delegation with cycle/depth detection
    - ``ContextBuilder`` — prompt assembly, token budgeting, memory retrieval
    - ``ToolCallTracker`` — per-turn failure classification and tool suppression
      (``disabled_tools`` set; registry never mutated)
    - ``MissionManager`` — async background task execution
    - ``AnswerVerifier`` — optional self-critique quality gate

    Turn-scoped tool suppression: when a tool hits ``ToolCallTracker.REMOVE_THRESHOLD``
    failures or classifies as permanently failed, it is added to a local
    ``disabled_tools: set[str]`` inside ``_run_agent_loop``.  The registry is not
    mutated, so the tool is available again in the next turn.
    """

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        config: AgentConfig,
        *,
        brave_api_key: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        role_config: AgentRoleConfig | None = None,
        routing_config: RoutingConfig | None = None,
        tool_registry: ToolRegistry | None = None,
    ):
        self._injected_tool_registry = tool_registry
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.config = config
        self.workspace = config.workspace_path
        self.role_config = role_config
        self.role_name = role_config.name if role_config else ""
        # Role overrides for model, temperature, max_iterations
        self.model = (
            (role_config.model if role_config and role_config.model else None)
            or config.model
            or provider.get_default_model()
        )
        self.max_iterations = (
            role_config.max_iterations
            if role_config and role_config.max_iterations is not None
            else config.max_iterations
        )
        self.temperature = (
            role_config.temperature
            if role_config and role_config.temperature is not None
            else config.temperature
        )
        self.memory_rollout_overrides = {
            "memory_rollout_mode": config.memory_rollout_mode,
            "memory_type_separation_enabled": config.memory_type_separation_enabled,
            "memory_router_enabled": config.memory_router_enabled,
            "memory_reflection_enabled": config.memory_reflection_enabled,
            "memory_shadow_mode": config.memory_shadow_mode,
            "memory_shadow_sample_rate": config.memory_shadow_sample_rate,
            "memory_vector_health_enabled": config.memory_vector_health_enabled,
            "memory_auto_reindex_on_empty_vector": config.memory_auto_reindex_on_empty_vector,
            "memory_history_fallback_enabled": config.memory_history_fallback_enabled,
            "conflict_auto_resolve_gap": config.memory_conflict_auto_resolve_gap,
            "memory_fallback_allowed_sources": config.memory_fallback_allowed_sources
            or ["profile", "events", "mem0_get_all"],
            "memory_fallback_max_summary_chars": config.memory_fallback_max_summary_chars,
            "rollout_gates": {
                "min_recall_at_k": config.memory_rollout_gate_min_recall_at_k,
                "min_precision_at_k": config.memory_rollout_gate_min_precision_at_k,
                "max_avg_memory_context_tokens": config.memory_rollout_gate_max_avg_memory_context_tokens,
                "max_history_fallback_ratio": config.memory_rollout_gate_max_history_fallback_ratio,
            },
            "graph_enabled": config.graph_enabled,
            "reranker_mode": config.reranker_mode,
            "reranker_alpha": config.reranker_alpha,
            "reranker_model": config.reranker_model,
            "mem0_user_id": config.mem0_user_id,
            "mem0_add_debug": config.mem0_add_debug,
            "mem0_verify_write": config.mem0_verify_write,
            "mem0_force_infer_true": config.mem0_force_infer_true,
        }
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service

        self.memory = MemoryStore(
            self.workspace,
            rollout_overrides=self.memory_rollout_overrides,
        )
        self.context = ContextBuilder(
            self.workspace,
            memory=self.memory,
            memory_retrieval_k=self.config.memory_retrieval_k if config.memory_enabled else 0,
            memory_token_budget=self.config.memory_token_budget if config.memory_enabled else 0,
            memory_md_token_cap=config.memory_md_token_cap if config.memory_enabled else 0,
            role_system_prompt=role_config.system_prompt if role_config else "",
        )
        self.sessions = session_manager or SessionManager(self.workspace)
        self._build_tools()
        self._wire_memory()
        self._register_handlers()

        self._running = False
        self._stop_event: asyncio.Event | None = None  # created lazily in run()
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False

        # Multi-agent coordinator (initialized lazily in run() if routing enabled)
        self._routing_config = routing_config
        self._coordinator: Coordinator | None = None

        # Delegation dispatcher (owns delegation state, tracing, contracts)
        self._dispatcher = DelegationDispatcher(
            config=DelegationConfig(
                workspace=self.workspace,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.config.max_tokens,
                max_iterations=self.max_iterations,
                restrict_to_workspace=self.config.restrict_to_workspace,
                brave_api_key=brave_api_key,
                exec_config=self.exec_config,
                role_name=self.role_name,
            ),
            provider=provider,
            max_delegation_depth=config.max_delegation_depth,
        )
        self._dispatcher.tools = self.tools

        # Unified delegation decision point (replaces 3 independent triggers)
        from nanobot.agent.delegation_advisor import DelegationAdvisor

        self._delegation_advisor = DelegationAdvisor()
        self._last_classification_result: ClassificationResult | None = None

        # Per-turn role switching (LAN-214)
        self._role_manager = TurnRoleManager(self)

        # Legacy aliases — kept for backward compat with tests
        self._delegation_stack: list[str] = []
        self._scratchpad: Scratchpad | None = None

        # Extracted helpers (ADR-002)
        self._llm_caller = StreamingLLMCaller(
            provider=provider,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.config.max_tokens,
        )
        self._verifier = AnswerVerifier(
            provider=provider,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.config.max_tokens,
            verification_mode=config.verification_mode,
            memory_uncertainty_threshold=self.config.memory_uncertainty_threshold,
            memory_store=self.context.memory,
        )

        # Per-turn token accumulators (reset in _run_agent_loop / TurnOrchestrator)
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        # TurnOrchestrator: owns the PAOR state machine (Task 6 decomposition).
        self._orchestrator = TurnOrchestrator(
            llm_caller=self._llm_caller,
            tool_executor=self.tools,
            verifier=self._verifier,
            dispatcher=self._dispatcher,
            delegation_advisor=self._delegation_advisor,
            config=self.config,
            prompts=prompts,
            context=self.context,
            provider=self.provider,
            model=self.model,
            max_iterations=self.max_iterations,
            role_name=self.role_name,
        )

        # MessageProcessor: per-message pipeline (Task 3 decomposition).
        self._processor = MessageProcessor(
            orchestrator=self._orchestrator,
            context=self.context,
            sessions=self.sessions,
            tools=self.tools,
            consolidator=self._consolidator,  # type: ignore[has-type]
            verifier=self._verifier,
            bus=self.bus,
            config=self.config,
            workspace=self.workspace,
            role_name=self.role_name,
            role_manager=self._role_manager,
            provider=self.provider,
            model=self.model,
        )
        # Share consolidation state: processor owns the mutable sets, AgentLoop
        # aliases them for backward compatibility with tests that access
        # loop._consolidating or loop._consolidation_tasks directly.
        self._consolidating: set[str] = self._processor._consolidating  # type: ignore[no-redef]
        self._consolidation_tasks: set[asyncio.Task[None]] = self._processor._consolidation_tasks  # type: ignore[no-redef]
        self._consolidation_sem = self._processor._consolidation_sem

        # Backward compat: tests may monkey-patch loop._consolidate_memory.
        # Store a reference that the processor resolves at call time so
        # patches on AgentLoop take effect.
        self._processor._consolidate_memory_ref = self  # type: ignore[attr-defined]

        # Wire token counter source: _run_agent_loop updates self._turn_tokens_*
        # on AgentLoop; the processor syncs from this reference before reading.
        self._processor._token_source = self

        # Wire span module so that tests patching
        # nanobot.agent.loop.update_current_span see their patches take effect.
        import nanobot.agent.loop as _loop_module

        self._processor._span_module = _loop_module

    def _build_tools(self) -> None:
        """Construct and wire the tool/capability layer.

        Called once from ``__init__`` after ``ContextBuilder`` and ``SessionManager``
        are ready.  Extracted from the constructor to keep ``__init__`` focused on
        pure attribute assignment (LAN-103).
        """
        if self._injected_tool_registry is not None:
            _tool_registry = self._injected_tool_registry
        else:
            _tool_registry = ToolRegistry()
        self._capabilities = CapabilityRegistry(
            tool_registry=_tool_registry,
            skills_loader=self.context.skills,
        )
        self.tools = ToolExecutor(_tool_registry)
        self.result_cache = ToolResultCache(workspace=self.workspace)
        self._capabilities.tool_registry.set_cache(
            self.result_cache,
            provider=self.provider,
            summary_model=self.config.tool_summary_model or None,
        )
        self.context.set_unavailable_tools_fn(self._capabilities.get_unavailable_summary)
        self.missions = MissionManager(
            provider=self.provider,
            workspace=self.workspace,
            bus=self.bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.config.max_tokens,
            max_iterations=self.config.mission_max_iterations,
            max_concurrent=self.config.mission_max_concurrent,
            result_max_chars=self.config.mission_result_max_chars,
            brave_api_key=self.brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=self.config.restrict_to_workspace,
        )
        if self._injected_tool_registry is None:
            self._register_default_tools()
        # Cache typed tool references for O(1) context updates in _set_tool_context.
        # Populated once at construction — no per-message isinstance checks needed.
        _msg_t = self.tools.get("message")
        self._ctx_message_tool: MessageTool | None = (
            _msg_t if isinstance(_msg_t, MessageTool) else None
        )
        _fb_t = self.tools.get("feedback")
        self._ctx_feedback_tool: FeedbackTool | None = (
            _fb_t if isinstance(_fb_t, FeedbackTool) else None
        )
        _ms_t = self.tools.get("mission_start")
        self._ctx_mission_tool: MissionStartTool | None = (
            _ms_t if isinstance(_ms_t, MissionStartTool) else None
        )
        _cr_t = self.tools.get("cron")
        self._ctx_cron_tool: CronTool | None = _cr_t if isinstance(_cr_t, CronTool) else None

    def _wire_memory(self) -> None:
        """Set up the memory consolidation subsystem.

        Called once from __init__ after _build_tools(). Initialises consolidation
        state and the ConsolidationOrchestrator that wraps self.context.memory.
        """
        self._consolidating: set[str] = set()  # type: ignore[no-redef]
        self._consolidation_tasks: set[asyncio.Task[None]] = set()  # type: ignore[no-redef]
        self._consolidation_sem = asyncio.Semaphore(3)  # Cap concurrent consolidation LLM calls
        self._consolidator = ConsolidationOrchestrator(self.context.memory)

    def _register_handlers(self) -> None:
        """Register bus message handlers.

        This agent uses a pull-based bus model (consume_inbound() in run()), so
        no pub/sub subscriptions are set up at construction time. This method
        exists as a named seam for future extension or subclass overrides.
        """

    def _register_default_tools(self) -> None:
        """Register the default set of tools, filtered by role config."""
        register_default_tools(
            tools=self.tools,
            role_config=self.role_config,
            workspace=self.workspace,
            restrict_to_workspace=self.config.restrict_to_workspace,
            shell_mode=self.config.shell_mode,
            vision_model=self.config.vision_model,
            exec_config=self.exec_config,
            brave_api_key=self.brave_api_key,
            publish_outbound=self.bus.publish_outbound,
            cron_service=self.cron_service,
            delegation_enabled=self.config.delegation_enabled,
            missions=self.missions,
            result_cache=self.result_cache,
            skills_enabled=self.config.skills_enabled,
            skills_loader=self.context.skills,
        )

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(
                self._mcp_servers,
                self._capabilities.tool_registry,
                self._mcp_stack,
            )
            self._mcp_connected = True
            # Share MCP tools with missions and delegation
            mcp_tools = [
                t
                for name in self._capabilities.tool_registry.tool_names
                if name.startswith("mcp_") and (t := self._capabilities.tool_registry.get(name))
            ]
            if mcp_tools:
                self.missions.mcp_tools = mcp_tools
                self._dispatcher.mcp_tools = mcp_tools
        except (RuntimeError, ConnectionError, OSError, TimeoutError, ImportError) as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except (RuntimeError, OSError):
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def set_deliver_callback(
        self,
        callback: Callable[[OutboundMessage], Awaitable[DeliveryResult | None]],
    ) -> None:
        """Replace the MessageTool send callback with an honest delivery path."""
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.set_send_callback(callback)

    def set_contacts_provider(
        self,
        provider: Callable[[], list[str]],
    ) -> None:
        """Set a callback that returns known email contacts (refreshed per-turn)."""
        self._contacts_provider = provider
        self._processor._contacts_provider = provider  # forward to processor

    def set_email_fetch(
        self,
        fetch_callback: Callable[..., list[dict[str, Any]]],
        fetch_unread_callback: Callable[..., list[dict[str, Any]]],
    ) -> None:
        """Wire email fetch callbacks into the CheckEmailTool."""
        if tool := self.tools.get("check_email"):
            if isinstance(tool, CheckEmailTool):
                tool._fetch = fetch_callback
                tool._fetch_unread = fetch_unread_callback

    def _refresh_contacts(self) -> None:
        """Pull latest contacts from the provider into the context builder."""
        if hasattr(self, "_contacts_provider"):
            self.context.set_contacts_context(self._contacts_provider())

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        self._refresh_contacts()
        if self._ctx_message_tool:
            self._ctx_message_tool.set_context(channel, chat_id, message_id)
        if self._ctx_mission_tool:
            self._ctx_mission_tool.set_context(channel, chat_id)
        if self._ctx_cron_tool:
            self._ctx_cron_tool.set_context(channel, chat_id)
        if self._ctx_feedback_tool:
            self._ctx_feedback_tool.set_context(
                channel,
                chat_id,
                session_key=f"{channel}:{chat_id}",
            )

    def _ensure_scratchpad(self, session_key: str) -> None:
        """Initialise (or swap) the per-session scratchpad and update tools."""
        from nanobot.utils.helpers import safe_filename

        safe_key = safe_filename(session_key.replace(":", "_"))
        session_dir = self.workspace / "sessions" / safe_key
        session_dir.mkdir(parents=True, exist_ok=True)
        self._scratchpad = Scratchpad(session_dir)
        self._dispatcher.scratchpad = self._scratchpad
        self._dispatcher._trace_path = session_dir / "routing_trace.jsonl"
        self.missions.scratchpad = self._scratchpad

        # Update scratchpad tool references
        write_tool = self.tools.get("write_scratchpad")
        if isinstance(write_tool, ScratchpadWriteTool):
            write_tool._scratchpad = self._scratchpad
        read_tool = self.tools.get("read_scratchpad")
        if isinstance(read_tool, ScratchpadReadTool):
            read_tool._scratchpad = self._scratchpad

    # ------------------------------------------------------------------
    # Backward-compat static method — delegates to module-level function
    # in turn_orchestrator.py.  Tests reference AgentLoop._needs_planning.
    # ------------------------------------------------------------------

    @staticmethod
    def _needs_planning(text: str) -> bool:  # pragma: no cover — delegate
        """Heuristic: does this message benefit from explicit planning?"""
        return _needs_planning(text)

    # ------------------------------------------------------------------
    # Agent loop delegation to TurnOrchestrator
    # ------------------------------------------------------------------

    async def _run_agent_loop(
        self,
        initial_messages: list[dict[str, Any]],
        on_progress: ProgressCallback | None = None,
    ) -> tuple[str | None, list[str], list[dict[str, Any]]]:
        """Run the Plan-Act-Observe-Reflect agent loop.

        Delegates to ``TurnOrchestrator.run()`` and unpacks the ``TurnResult``
        into the legacy 3-tuple format for backward compatibility with
        ``MessageProcessor._LegacyOrchestrator`` and any callers that still
        reference this method directly.

        Returns ``(final_content, tools_used, messages)``.
        """
        # Extract the last user message (used by planning + verification)
        user_text = ""
        for m in reversed(initial_messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str):
                    user_text = content
                elif isinstance(content, list):
                    user_text = " ".join(
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                break

        state = TurnState(
            messages=initial_messages,
            user_text=user_text,
            tools_def_cache=list(self.tools.get_definitions()),
        )

        # Forward coordinator classification to the orchestrator
        self._orchestrator._last_classification_result = self._last_classification_result

        result = await self._orchestrator.run(state, on_progress)

        # Sync token counters back to AgentLoop for the processor to read
        self._turn_tokens_prompt = self._orchestrator._turn_tokens_prompt
        self._turn_tokens_completion = self._orchestrator._turn_tokens_completion
        self._turn_llm_calls = self._orchestrator._turn_llm_calls

        return result.content or None, result.tools_used, result.messages

    # ------------------------------------------------------------------
    # Reaction handling (Step 8 — Feedback loop)
    # ------------------------------------------------------------------

    async def handle_reaction(self, reaction: ReactionEvent) -> None:
        """Translate an emoji reaction from a channel into a feedback event.

        Channels can call this when a user adds a reaction to a bot message.
        The reaction is mapped to positive/negative and persisted via the
        feedback tool.
        """
        rating = classify_reaction(reaction.emoji)
        if rating is None:
            logger.debug("Ignoring unmapped reaction emoji: {}", reaction.emoji)
            return

        feedback_tool = self.tools.get("feedback")
        if not isinstance(feedback_tool, FeedbackTool):
            return

        feedback_tool.set_context(
            reaction.channel,
            reaction.chat_id,
            session_key=f"{reaction.channel}:{reaction.chat_id}",
        )
        result = await feedback_tool.execute(
            rating=rating,
            comment=f"emoji reaction: {reaction.emoji}",
            topic="",
        )
        logger.info(
            "Reaction {} from {}:{} → {}",
            reaction.emoji,
            reaction.channel,
            reaction.sender_id,
            "ok" if result.success else result.error,
        )

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus.

        When multi-agent routing is enabled (``routing_config.enabled``),
        each inbound message is first classified by the coordinator.  The
        coordinator returns an ``AgentRoleConfig`` whose overrides
        (model, system prompt, tool filters) are applied for that turn
        via ``TurnRoleManager.apply``.  When routing is disabled the loop
        behaves exactly as before.
        """
        self._running = True
        self._stop_event = asyncio.Event()
        await self._connect_mcp()
        self._ensure_coordinator()
        await self.context.memory.maintenance.ensure_health()  # LAN-101: non-blocking vector health

        logger.info("Agent loop started")

        while self._running:
            try:
                # Race consume_inbound against the stop event so that stop()
                # wakes the loop immediately instead of waiting up to 5 s.
                _consume = asyncio.create_task(self.bus.consume_inbound())
                _stop_wait = asyncio.create_task(self._stop_event.wait())  # type: ignore[union-attr]
                done, pending = await asyncio.wait(
                    {_consume, _stop_wait},
                    timeout=5.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if not self._running or _stop_wait in done:
                    break
                if _consume not in done:
                    # True timeout — no message, no stop signal
                    continue
                msg = _consume.result()
                turn_ctx: TurnContext | None = None
                # Set correlation IDs for this request
                TraceContext.new_request(
                    session_id=msg.session_key,
                    agent_id=self.role_name,
                )

                # Detach any stale OTEL span context from a previous iteration
                # to prevent context leaks that silently orphan all subsequent
                # traces (see ADR-005 / Langfuse v4 hardening).
                reset_trace_context()

                try:
                    # Route through coordinator if enabled (skip system messages)

                    # Wrap entire request (classify + process) in a single trace
                    async with trace_request(
                        name="request",
                        input=msg.content[:200],
                        session_id=msg.session_key,
                        user_id=msg.sender_id,
                        tags=[msg.channel],
                        metadata={
                            "channel": msg.channel,
                            "sender": msg.sender_id,
                            "session_key": msg.session_key,
                            "model": self.model,
                            "role": self.role_name,
                        },
                    ):
                        if self._coordinator and msg.channel != "system":
                            t0_classify = time.monotonic()
                            cls_result = await self._coordinator.classify(msg.content)
                            self._last_classification_result = cls_result
                            role_name, confidence = cls_result.role_name, cls_result.confidence
                            classify_latency_ms = (time.monotonic() - t0_classify) * 1000
                            # Confidence-aware: fall back to default on low confidence
                            threshold = (
                                self._routing_config.confidence_threshold
                                if self._routing_config
                                else _DEFAULT_CONFIDENCE_THRESHOLD
                            )
                            if confidence < threshold:
                                role_name = (
                                    self._routing_config.default_role
                                    if self._routing_config
                                    else "general"
                                )
                                logger.info(
                                    "Low confidence ({:.2f} < {:.2f}), using default role '{}'",
                                    confidence,
                                    threshold,
                                    role_name,
                                )
                            role = (
                                self._coordinator.route_direct(role_name)
                                or self._coordinator.registry.get_default()
                                or AgentRoleConfig(name=role_name, description="General assistant")
                            )
                            self._dispatcher.record_route_trace(
                                "route",
                                role=role.name,
                                confidence=confidence,
                                latency_ms=classify_latency_ms,
                                message_excerpt=msg.content,
                            )
                            turn_ctx = self._role_manager.apply(role)

                        # Wrap with timeout to prevent infinite processing
                        timeout = (
                            self.config.message_timeout if self.config.message_timeout > 0 else None
                        )
                        try:
                            if timeout:
                                response = await asyncio.wait_for(
                                    self._process_message(msg), timeout=timeout
                                )
                            else:
                                response = await self._process_message(msg)
                        except asyncio.TimeoutError:
                            logger.error(
                                "Message processing timed out after {}s for {}:{}",
                                self.config.message_timeout,
                                msg.channel,
                                msg.chat_id,
                            )
                            update_current_span(
                                output="TIMEOUT",
                                metadata={"timeout_s": str(self.config.message_timeout)},
                                level="ERROR",
                            )
                            response = OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content=(
                                    "Sorry, I ran out of time processing your request. "
                                    "Try breaking it into smaller steps."
                                ),
                            )

                    self._role_manager.reset(turn_ctx)

                    if response is not None:
                        await self.bus.publish_outbound(response)
                    elif msg.channel in {"cli", "telegram"}:
                        await self.bus.publish_outbound(
                            OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content="",
                                metadata=msg.metadata or {},
                            )
                        )

                    # Explicit flush: the gateway run() loop never calls
                    # shutdown_langfuse() during normal operation, so without
                    # this, traces rely on the OTEL BatchSpanProcessor timer.
                    # Flushing per-request guarantees delivery.
                    flush_langfuse()

                except Exception as e:  # crash-barrier: message processing
                    logger.exception("Error processing message")
                    self._role_manager.reset(turn_ctx)
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=_user_friendly_error(e),
                        )
                    )
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------------
    # Delegation dispatch
    # ------------------------------------------------------------------

    def _ensure_coordinator(self) -> None:
        """Lazy-initialise the multi-agent coordinator if routing is enabled."""
        if not self._routing_config or not self._routing_config.enabled:
            return
        if self._coordinator is not None:
            return

        from nanobot.agent.coordinator import DEFAULT_ROLES, Coordinator

        for role in DEFAULT_ROLES:
            self._capabilities.register_role(role)
        for role_cfg in self._routing_config.roles:
            self._capabilities.merge_register_role(role_cfg)
        registry = self._capabilities.agent_registry
        registry._default_role = self._routing_config.default_role
        self._coordinator = Coordinator(
            provider=self.provider,
            registry=registry,
            classifier_model=self._routing_config.classifier_model,
            default_role=self._routing_config.default_role,
            confidence_threshold=self._routing_config.confidence_threshold,
        )
        self._dispatcher.coordinator = self._coordinator
        self.missions.coordinator = self._coordinator
        self._dispatcher.wire_delegate_tools(
            available_roles_fn=self._capabilities.role_names,
        )

        logger.info(
            "Multi-agent routing enabled with {} roles",
            len(registry),
        )

    async def close_mcp(self) -> None:
        """Close MCP connections and other async resources."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except RuntimeError:
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None
        try:
            await self.provider.aclose()
        except (RuntimeError, OSError, AttributeError) as e:
            logger.debug("Provider cleanup failed: {}", e)
        if hasattr(self, "memory_store") and self.memory_store.graph:
            try:
                await self.memory_store.graph.close()
            except (RuntimeError, OSError) as e:
                logger.debug("Graph driver cleanup failed: {}", e)

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        logger.info("Agent loop stopping")

    async def _run_consolidation_task(self, session: Session, lock: asyncio.Lock) -> None:
        """Run one consolidation pass; holds the semaphore and per-session lock."""
        try:
            async with self._consolidation_sem:
                async with lock:
                    await self._consolidate_memory(session)
        finally:
            self._consolidating.discard(session.key)
            self._consolidator.prune_lock(session.key, lock)

    def _make_bus_progress(
        self,
        channel: str,
        chat_id: str,
        base_meta: dict[str, Any],
        canonical_builder: CanonicalEventBuilder,
    ) -> ProgressCallback:
        """Delegate to the standalone make_bus_progress factory."""
        return make_bus_progress(
            bus=self.bus,
            channel=channel,
            chat_id=chat_id,
            base_meta=base_meta,
            canonical_builder=canonical_builder,
        )

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> OutboundMessage | None:
        """Delegate to MessageProcessor.

        This method is kept on ``AgentLoop`` for backward compatibility with
        tests and callers that monkey-patch ``_process_message``.  The real
        implementation lives in ``MessageProcessor._process_message``.
        """
        return await self._processor._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
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

    async def _consolidate_memory(self, session: Session, archive_all: bool = False) -> bool:
        """Delegate to ConsolidationOrchestrator.

        Kept on AgentLoop for backward compatibility with tests that
        monkey-patch ``loop._consolidate_memory``.  The processor routes
        through this method via ``_consolidate_memory_ref``.
        """
        return await self._consolidator.consolidate(
            session,
            self.provider,
            self.model,
            memory_window=self.config.memory_window,
            enable_contradiction_check=self.config.memory_enable_contradiction_check,
            archive_all=archive_all,
        )

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

        When *forced_role* is provided the coordinator is initialised but
        classification is skipped — the named role is applied directly for
        this turn.  This is used by ``nanobot routing replay`` to re-process
        a misrouted message under a corrected role.
        """
        await self._connect_mcp()
        self._ensure_coordinator()
        self._last_classification_result = None

        # Resolve forced role (if any) before entering the trace context so
        # that the role name is included in the trace metadata.
        turn_ctx: TurnContext | None = None
        if forced_role:
            role = self._coordinator.route_direct(forced_role) if self._coordinator else None
            if role is None:
                logger.warning(
                    "Unknown forced role '{}' — available roles not matched", forced_role
                )
                return f"Unknown role: {forced_role}"
            turn_ctx = self._role_manager.apply(role)

        try:
            async with trace_request(
                name="request",
                input=content[:200],
                session_id=session_key,
                user_id="cli",
                tags=[channel],
                metadata={
                    "channel": channel,
                    "sender": "user",
                    "session_key": session_key,
                    "model": self.model,
                    "role": self.role_name,
                },
            ):
                return await self._processor.process_direct(
                    content, session_key, channel, chat_id, on_progress, forced_role
                )
        finally:
            self._role_manager.reset(turn_ctx)
