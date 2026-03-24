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
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.bus_progress import make_bus_progress
from nanobot.agent.callbacks import ProgressCallback
from nanobot.agent.observability import (
    flush as flush_langfuse,
)
from nanobot.agent.observability import (
    reset_trace_context,
    trace_request,
    update_current_span,
)
from nanobot.agent.reaction import classify_reaction
from nanobot.agent.tracing import TraceContext
from nanobot.agent.turn_types import TurnState
from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.bus.events import DeliveryResult, InboundMessage, OutboundMessage, ReactionEvent
from nanobot.config.schema import AgentRoleConfig
from nanobot.coordination.role_switching import TurnContext
from nanobot.session.manager import Session
from nanobot.tools.builtin.email import CheckEmailTool
from nanobot.tools.builtin.feedback import FeedbackTool
from nanobot.tools.builtin.message import MessageTool

if TYPE_CHECKING:
    from nanobot.agent.agent_components import _AgentComponents
    from nanobot.coordination.coordinator import ClassificationResult, Coordinator


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

    def __init__(self, *, components: _AgentComponents) -> None:
        # Config and identity
        self.bus = components.bus
        self.provider = components.provider
        self.config = components.config
        self.workspace = components.core.workspace
        self.model = components.core.model
        self.temperature = components.core.temperature
        self.max_iterations = components.core.max_iterations
        self.role_config = components.core.role_config
        self.role_name = components.core.role_name
        self.channels_config = components.infra.channels_config
        self.brave_api_key = components.infra.brave_api_key
        self.exec_config = components.infra.exec_config
        self.cron_service = components.infra.cron_service
        self.memory_rollout_overrides = components.infra.memory_rollout_overrides

        # Subsystems
        self.memory = components.subsystems.memory
        self.context = components.subsystems.context
        self.sessions = components.subsystems.sessions
        self.tools = components.subsystems.tools
        self._capabilities = components.subsystems.capabilities
        self.result_cache = components.subsystems.result_cache
        self.missions = components.subsystems.missions
        self._consolidator = components.subsystems.consolidator
        self._dispatcher = components.subsystems.dispatcher
        self._delegation_advisor = components.subsystems.delegation_advisor
        self._llm_caller = components.subsystems.llm_caller
        self._verifier = components.subsystems.verifier
        self._orchestrator = components.subsystems.orchestrator
        self._processor = components.subsystems.processor
        self._role_manager = components.role_manager

        # Routing
        self._routing_config = components.infra.routing_config
        self._mcp_servers = components.infra.mcp_servers

        # Runtime state (not constructed)
        self._running = False
        self._stop_event: asyncio.Event | None = None
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._coordinator: Coordinator | None = None
        self._last_classification_result: ClassificationResult | None = None
        self._delegation_stack: list[str] = []
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register bus message handlers.

        This agent uses a pull-based bus model (consume_inbound() in run()), so
        no pub/sub subscriptions are set up at construction time. This method
        exists as a named seam for future extension or subclass overrides.
        """

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.tools.builtin.mcp import connect_mcp_servers

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
        into the legacy 3-tuple format for backward compatibility with any
        callers that still reference this method directly.

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
            classification_result=self._last_classification_result,
            tools_def_cache=list(self.tools.get_definitions()),
        )

        result = await self._orchestrator.run(state, on_progress)

        # Read token counters from TurnResult
        self._turn_tokens_prompt = result.tokens_prompt
        self._turn_tokens_completion = result.tokens_completion
        self._turn_llm_calls = result.llm_calls

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
        assert self._role_manager is not None, "build_agent() must wire _role_manager"
        self._running = True
        self._stop_event = asyncio.Event()
        await self._connect_mcp()
        self._ensure_coordinator()
        await self.context.memory.maintenance.ensure_health()  # LAN-101: non-blocking vector health

        logger.info("Agent loop started")

        # The consolidation orchestrator context enables submit() to schedule
        # background tasks.  __aexit__ drains all pending tasks on shutdown.
        async with self._consolidator:
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
                                self._processor.set_classification_result(cls_result)
                                role_name, confidence = (
                                    cls_result.role_name,
                                    cls_result.confidence,
                                )
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
                                    or AgentRoleConfig(
                                        name=role_name,
                                        description="General assistant",
                                    )
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
                                self.config.message_timeout
                                if self.config.message_timeout > 0
                                else None
                            )
                            try:
                                if timeout:
                                    response = await asyncio.wait_for(
                                        self._process_message(msg),
                                        timeout=timeout,
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
                                        "Sorry, I ran out of time processing"
                                        " your request. "
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
                        # shutdown_langfuse() during normal operation, so
                        # without this, traces rely on the OTEL
                        # BatchSpanProcessor timer.
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

        from nanobot.coordination.coordinator import DEFAULT_ROLES, Coordinator

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
        if hasattr(self, "memory") and self.memory.graph:
            try:
                await self.memory.graph.close()
            except (RuntimeError, OSError) as e:
                logger.debug("Graph driver cleanup failed: {}", e)

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        logger.info("Agent loop stopping")

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

    async def _consolidate_memory(self, session: Session, archive_all: bool = False) -> bool:
        """Delegate to ConsolidationOrchestrator."""
        if archive_all:
            return await self._consolidator.consolidate_and_wait(
                session.key,
                session,
                self.provider,
                self.model,
                archive_all=True,
            )
        self._consolidator.submit(session.key, session, self.provider, self.model)
        return True

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
        assert self._role_manager is not None, "build_agent() must wire _role_manager"
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
