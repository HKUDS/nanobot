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
import json
import time
import uuid
import weakref
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, Protocol

from loguru import logger

from nanobot.agent.capability import CapabilityRegistry
from nanobot.agent.consolidation import ConsolidationOrchestrator
from nanobot.agent.context import (
    ContextBuilder,
    estimate_messages_tokens,
    summarize_and_compress,
)
from nanobot.agent.delegation import DelegationDispatcher
from nanobot.agent.failure import FailureClass, ToolCallTracker, _build_failure_prompt
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
from nanobot.agent.scratchpad import Scratchpad
from nanobot.agent.streaming import StreamingLLMCaller, strip_think
from nanobot.agent.tool_executor import ToolExecutor
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.delegate import DelegateParallelTool, DelegateTool, DelegationResult
from nanobot.agent.tools.email import CheckEmailTool
from nanobot.agent.tools.excel import (
    DescribeDataTool,
    ExcelFindTool,
    ExcelGetRowsTool,
    QueryDataTool,
    ReadSpreadsheetTool,
)
from nanobot.agent.tools.feedback import FeedbackTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.mission import (
    MissionCancelTool,
    MissionListTool,
    MissionStartTool,
    MissionStatusTool,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.result_cache import CacheGetSliceTool, ToolResultCache
from nanobot.agent.tools.scratchpad import ScratchpadReadTool, ScratchpadWriteTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.agent.tracing import TraceContext, bind_trace
from nanobot.agent.verifier import AnswerVerifier
from nanobot.bus.canonical import CanonicalEventBuilder
from nanobot.bus.events import DeliveryResult, InboundMessage, OutboundMessage, ReactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig, AgentRoleConfig, ExecToolConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.coordinator import Coordinator
    from nanobot.config.schema import ChannelsConfig, RoutingConfig
    from nanobot.cron.service import CronService


# Per-coroutine delegation ancestry — canonical definition in delegation.py,
# re-exported here for backward compatibility with tests.
from nanobot.agent.delegation import _delegation_ancestry  # noqa: F401

# Tools whose arguments may contain sensitive data (file contents, credentials,
# command strings). Their call arguments are omitted from structured log output
# to prevent leaking sensitive information into log files or tracing backends.
_ARGS_REDACT_TOOLS: frozenset[str] = frozenset(
    {"write_file", "edit_file", "exec", "web_fetch", "web_search"}
)

# Delegation tool names — hoisted here to avoid rebuilding the set each iteration.
_DELEGATION_TOOL_NAMES: frozenset[str] = frozenset({"delegate", "delegate_parallel"})

# Named constants for magic numbers used across the agent loop (CQ-L6).
_GREETING_MAX_LEN: int = 20  # Messages shorter than this are treated as greetings / simple Qs
_CONTEXT_RESERVE_RATIO: float = (
    0.80  # Fraction of context window reserved for prompt; ~20% for reply
)
_DEFAULT_CONFIDENCE_THRESHOLD: float = (
    0.6  # Fallback routing confidence threshold (no RoutingConfig)
)

# Multi-step planning signal substrings for _needs_planning().
# Defined at module level so the tuple is allocated once, not per call.
_PLANNING_SIGNALS: tuple[str, ...] = (
    " and ",
    " then ",
    " after that",
    " also ",
    " steps",
    " first ",
    " second ",
    " finally ",
    "\n-",
    "\n*",
    "\n1.",
    "\n2.",
    " research ",
    " analyze ",
    " compare ",
    " investigate ",
    " create ",
    " build ",
    " implement ",
    " set up ",
    " configure ",
    " plan ",
    " schedule ",
    " organize ",
)


class ProgressCallback(Protocol):
    """Signature for progress callbacks passed through the agent call chain.

    Matches the ``_bus_progress`` closure created in ``_process_message``.
    External callers may pass a simpler ``async def cb(content: str) -> None``
    via ``process_direct``; that path does not use keyword arguments.
    """

    async def __call__(
        self,
        content: str,
        *,
        tool_hint: bool = ...,
        streaming: bool = ...,
        tool_call: dict | None = ...,
        tool_result: dict | None = ...,
        delegate_start: dict | None = ...,
        delegate_end: dict | None = ...,
        status_code: str = ...,
        status_label: str = ...,
    ) -> None:
        pass


@dataclass(slots=True)
class TurnContext:
    """Snapshot of agent settings overridden for a single routed turn.

    Created by ``_apply_role_for_turn`` and consumed by ``_reset_role_after_turn``
    to cleanly restore the original configuration without touching shared state
    between turns.
    """

    model: str
    temperature: float
    max_iterations: int
    role_prompt: str
    tools: dict[str, Any] | None  # None → no tool filtering was applied


@dataclass(slots=True)
class _ToolBatchResult:
    """Return value of ``_process_tool_results`` — scalar state that changes per batch."""

    any_failed: bool
    failed_this_batch: list[tuple[str, "FailureClass"]]
    nudged_for_final: bool
    last_tool_call_msg_idx: int
    tool_calls_this_batch: int


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


def _dynamic_preserve_recent(
    messages: list[dict[str, Any]],
    last_tool_call_idx: int = -1,
    *,
    floor: int = 6,
    cap: int = 30,
) -> int:
    """Calculate how many tail messages to preserve during compression.

    Ensures the last complete tool-call cycle (assistant with tool_calls →
    all corresponding tool results → next message) is never split.
    Falls back to *floor* when no tool calls are present.

    *last_tool_call_idx* is the index of the last assistant message that
    contained tool_calls.  When provided (>= 0), the backward scan is skipped
    entirely, making this function O(1).
    """
    n = len(messages)
    if n <= floor:
        return floor

    if last_tool_call_idx >= 0:
        needed = n - last_tool_call_idx
        return max(floor, min(needed, cap))

    # Fallback: scan backwards (O(n), bounded by cap) when index unknown
    for offset in range(1, n):
        idx = n - offset
        m = messages[idx]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            needed = n - idx
            return max(floor, min(needed, cap))
    return floor


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
    ):
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
            "graph_neo4j_uri": config.graph_neo4j_uri,
            "graph_neo4j_auth": config.graph_neo4j_auth,
            "graph_neo4j_database": config.graph_neo4j_database,
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

        self.context = ContextBuilder(
            self.workspace,
            memory_retrieval_k=self.config.memory_retrieval_k if config.memory_enabled else 0,
            memory_token_budget=self.config.memory_token_budget if config.memory_enabled else 0,
            memory_md_token_cap=config.memory_md_token_cap if config.memory_enabled else 0,
            memory_rollout_overrides=self.memory_rollout_overrides,
            role_system_prompt=role_config.system_prompt if role_config else "",
        )
        self.sessions = session_manager or SessionManager(self.workspace)
        self._build_tools()

        self._running = False
        self._stop_event: asyncio.Event | None = None  # created lazily in run()
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task[None]] = set()  # Strong refs to in-flight tasks
        self._consolidation_sem = asyncio.Semaphore(3)  # Cap concurrent consolidation LLM calls

        # Multi-agent coordinator (initialized lazily in run() if routing enabled)
        self._routing_config = routing_config
        self._coordinator: Coordinator | None = None

        # Delegation dispatcher (owns delegation state, tracing, contracts)
        self._dispatcher = DelegationDispatcher(
            provider=provider,
            workspace=self.workspace,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.config.max_tokens,
            max_iterations=self.max_iterations,
            restrict_to_workspace=self.config.restrict_to_workspace,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            role_name=self.role_name,
        )
        self._dispatcher.tools = self.tools

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
        self._consolidator = ConsolidationOrchestrator(self.context.memory)

        # Per-turn token accumulators (reset in _run_agent_loop)
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

    # --- Delegation state proxied to _dispatcher ---

    @property
    def _consolidation_locks(self) -> weakref.WeakValueDictionary[str, asyncio.Lock]:
        return self._consolidator._locks

    @property
    def _delegation_count(self) -> int:
        return self._dispatcher.delegation_count

    @_delegation_count.setter
    def _delegation_count(self, value: int) -> None:
        self._dispatcher.delegation_count = value

    @property
    def _max_delegations(self) -> int:
        return self._dispatcher.max_delegations

    @_max_delegations.setter
    def _max_delegations(self, value: int) -> None:
        self._dispatcher.max_delegations = value

    @property
    def _routing_trace(self) -> list[dict[str, Any]]:
        return self._dispatcher.routing_trace

    @property
    def _active_messages(self) -> list[dict[str, Any]] | None:
        return self._dispatcher.active_messages

    @_active_messages.setter
    def _active_messages(self, value: list[dict[str, Any]] | None) -> None:
        self._dispatcher.active_messages = value

    def _build_tools(self) -> None:
        """Construct and wire the tool/capability layer.

        Called once from ``__init__`` after ``ContextBuilder`` and ``SessionManager``
        are ready.  Extracted from the constructor to keep ``__init__`` focused on
        pure attribute assignment (LAN-103).
        """
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

    def _register_default_tools(self) -> None:
        """Register the default set of tools, filtered by role config."""
        role = self.role_config
        allowed = set(role.allowed_tools) if role and role.allowed_tools is not None else None
        denied = set(role.denied_tools) if role and role.denied_tools else set()
        allowed_dir = self.workspace if self.config.restrict_to_workspace else None

        def _should_register(name: str) -> bool:
            if allowed is not None and name not in allowed:
                return False
            return name not in denied

        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            tool = cls(workspace=self.workspace, allowed_dir=allowed_dir)
            if _should_register(tool.name):
                self.tools.register(tool)

        spreadsheet_tool = ReadSpreadsheetTool(
            workspace=self.workspace,
            allowed_dir=allowed_dir,
            cache=self.result_cache,
        )
        if _should_register(spreadsheet_tool.name):
            self.tools.register(spreadsheet_tool)

        exec_tool = ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.config.restrict_to_workspace,
            shell_mode=self.config.shell_mode,
        )
        if _should_register(exec_tool.name):
            self.tools.register(exec_tool)

        for extra_tool in (
            WebSearchTool(api_key=self.brave_api_key),
            WebFetchTool(),
            MessageTool(send_callback=self.bus.publish_outbound),
            FeedbackTool(events_file=self.workspace / "memory" / "events.jsonl"),
        ):
            if _should_register(extra_tool.name):
                self.tools.register(extra_tool)

        # Email checking tool (callback set later by gateway via set_email_fetch)
        email_tool = CheckEmailTool()
        if _should_register(email_tool.name):
            self.tools.register(email_tool)

        if self.cron_service:
            cron_tool = CronTool(self.cron_service)
            if _should_register(cron_tool.name):
                self.tools.register(cron_tool)

        # Delegation tools
        if self.config.delegation_enabled:
            delegate_tool = DelegateTool()
            if _should_register(delegate_tool.name):
                self.tools.register(delegate_tool)
            delegate_parallel_tool = DelegateParallelTool()
            if _should_register(delegate_parallel_tool.name):
                self.tools.register(delegate_parallel_tool)
            mission_tool = MissionStartTool(manager=self.missions)
            if _should_register(mission_tool.name):
                self.tools.register(mission_tool)
            mission_status = MissionStatusTool(manager=self.missions)
            if _should_register(mission_status.name):
                self.tools.register(mission_status)
            mission_list = MissionListTool(manager=self.missions)
            if _should_register(mission_list.name):
                self.tools.register(mission_list)
            mission_cancel = MissionCancelTool(manager=self.missions)
            if _should_register(mission_cancel.name):
                self.tools.register(mission_cancel)

        # Scratchpad tools (scratchpad instance swapped per session in _ensure_scratchpad)
        placeholder_pad = Scratchpad(self.workspace / "sessions" / "_placeholder")
        for st in (
            ScratchpadWriteTool(placeholder_pad),
            ScratchpadReadTool(placeholder_pad),
        ):
            if _should_register(st.name):
                self.tools.register(st)

        # Skill-provided custom tools (Step 14)
        if self.config.skills_enabled:
            for skill_tool in self.context.skills.discover_tools():
                self.tools.register(skill_tool)

        # Cache retrieval tools
        cache_slice = CacheGetSliceTool(cache=self.result_cache)
        if _should_register(cache_slice.name):
            self.tools.register(cache_slice)

        excel_rows = ExcelGetRowsTool(cache=self.result_cache)
        if _should_register(excel_rows.name):
            self.tools.register(excel_rows)

        excel_find = ExcelFindTool(cache=self.result_cache)
        if _should_register(excel_find.name):
            self.tools.register(excel_find)

        query_tool = QueryDataTool(cache=self.result_cache)
        if _should_register(query_tool.name):
            self.tools.register(query_tool)

        describe_tool = DescribeDataTool(cache=self.result_cache)
        if _should_register(describe_tool.name):
            self.tools.register(describe_tool)

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
        self.missions.scratchpad = self._scratchpad

        # Update scratchpad tool references
        write_tool = self.tools.get("write_scratchpad")
        if isinstance(write_tool, ScratchpadWriteTool):
            write_tool._scratchpad = self._scratchpad
        read_tool = self.tools.get("read_scratchpad")
        if isinstance(read_tool, ScratchpadReadTool):
            read_tool._scratchpad = self._scratchpad

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks — delegates to streaming module."""
        return strip_think(text)

    async def _call_llm(
        self,
        messages: list[dict],
        tools: list[dict[str, Any]] | None,
        on_progress: ProgressCallback | None,
    ) -> LLMResponse:
        """Call the LLM — delegates to StreamingLLMCaller."""
        return await self._llm_caller.call(messages, tools, on_progress)

    # ------------------------------------------------------------------
    # Agent loop (Plan → Act → Observe → Reflect)
    # ------------------------------------------------------------------
    # Planning & Reflection prompts
    # ------------------------------------------------------------------

    # Prompts loaded from nanobot/templates/prompts/*.md via PromptLoader.
    # Override by placing files in <workspace>/prompts/.

    @staticmethod
    def _needs_planning(text: str) -> bool:
        """Heuristic: does this message benefit from explicit planning?

        Short greetings, simple questions, or single-action requests don't
        need a plan. Multi-step tasks, research queries, and complex
        instructions do.
        """
        if not text:
            return False
        text_lower = text.strip().lower()
        # Very short messages (< 20 chars) are usually greetings or simple Qs
        if len(text_lower) < _GREETING_MAX_LEN:
            return False
        # Explicit multi-step indicators
        return any(signal in text_lower for signal in _PLANNING_SIGNALS)

    @staticmethod
    def _has_parallel_structure(text: str) -> bool:
        return DelegationDispatcher.has_parallel_structure(text)

    # ------------------------------------------------------------------
    # _run_agent_loop helpers (extracted for readability)
    # ------------------------------------------------------------------

    async def _handle_llm_error(
        self,
        response: "LLMResponse",
        consecutive_errors: int,
        messages: list[dict],
        on_progress: ProgressCallback | None,
    ) -> tuple[Literal["continue", "break", "proceed"], int, str | None]:
        """Handle LLM-level error finish reasons.

        Returns ``(action, consecutive_errors, final_content)`` where *action*
        is ``"continue"`` (retry this iteration), ``"break"`` (end the loop),
        or ``"proceed"`` (no error — continue normal processing).
        *messages* is mutated in-place when a final answer is injected.
        """
        if response.finish_reason == "error":
            consecutive_errors += 1
            logger.warning(
                "LLM returned error (attempt {}): {}", consecutive_errors, response.content
            )
            if consecutive_errors >= 3:
                final_content = (
                    "I'm having trouble reaching the language model right now. "
                    "Please try again in a moment."
                )
                messages[:] = self.context.add_assistant_message(messages, final_content)
                return "break", consecutive_errors, final_content
            if on_progress:
                await on_progress("", status_code="retrying")
            await asyncio.sleep(min(2**consecutive_errors, 10))
            return "continue", consecutive_errors, None

        if response.finish_reason == "content_filter":
            consecutive_errors += 1
            logger.warning("Content filter triggered (attempt {})", consecutive_errors)
            if consecutive_errors >= 2:
                final_content = (
                    "The AI provider's content filter blocked my response. "
                    "Try rephrasing your question."
                )
                messages[:] = self.context.add_assistant_message(messages, final_content)
                return "break", consecutive_errors, final_content
            await asyncio.sleep(1)
            return "continue", consecutive_errors, None

        if response.finish_reason == "length" and not response.content:
            consecutive_errors += 1
            logger.warning("Response truncated to zero content (attempt {})", consecutive_errors)
            if consecutive_errors >= 2:
                final_content = (
                    "My response was too long and got cut off. Try asking a more specific question."
                )
                messages[:] = self.context.add_assistant_message(messages, final_content)
                return "break", consecutive_errors, final_content
            await asyncio.sleep(1)
            return "continue", consecutive_errors, None

        return "proceed", consecutive_errors, None

    async def _process_tool_results(
        self,
        response: "LLMResponse",
        messages: list[dict],
        tools_used: list[str],
        disabled_tools: set[str],
        tracker: "ToolCallTracker",
        _tools_def_cache: list[dict],
        on_progress: ProgressCallback | None,
        nudged_for_final: bool,
    ) -> _ToolBatchResult:
        """Execute tool calls and process their results.

        Mutates *messages*, *tools_used*, and *disabled_tools* in-place.
        Returns a ``_ToolBatchResult`` with the scalar state changes.
        """
        _args_json: dict[str, str] = {
            tc.id: json.dumps(tc.arguments, ensure_ascii=False) for tc in response.tool_calls
        }
        tool_call_dicts = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": _args_json[tc.id]},
            }
            for tc in response.tool_calls
        ]
        # Suppress draft content when tool calls are present; keep as reasoning.
        reasoning = response.reasoning_content or response.content
        new_messages = self.context.add_assistant_message(
            messages,
            None,
            tool_call_dicts,
            reasoning_content=reasoning,
        )
        last_tool_call_msg_idx = len(new_messages) - 1
        messages[:] = new_messages

        # Execute tools (parallel for readonly, sequential for writes)
        t0_tools = time.monotonic()
        tool_results = await self.tools.execute_batch(response.tool_calls)
        tools_elapsed_ms = (time.monotonic() - t0_tools) * 1000

        any_failed = False
        failed_this_batch: list[tuple[str, FailureClass]] = []
        tools_to_remove: list[str] = []
        tool_calls_this_batch = 0
        for tool_call, result in zip(response.tool_calls, tool_results):
            tool_calls_this_batch += 1
            tools_used.append(tool_call.name)
            args_str = _args_json[tool_call.id]
            status = "OK" if result.success else "FAIL"
            bind_trace().info(
                "tool_exec | {} | {} | {:.0f}ms batch",
                status,
                tool_call.name,
                tools_elapsed_ms,
            )
            if tool_call.name not in _ARGS_REDACT_TOOLS:
                bind_trace().debug("tool_exec args | {}({})", tool_call.name, args_str[:200])
            if on_progress:
                await on_progress(
                    "",
                    tool_result={
                        "toolCallId": tool_call.id,
                        "result": result.to_llm_string(),
                    },
                )
            messages[:] = self.context.add_tool_result(
                messages, tool_call.id, tool_call.name, result.to_llm_string()
            )
            if not result.success:
                any_failed = True
                count, fc = tracker.record_failure(tool_call.name, tool_call.arguments, result)
                failed_this_batch.append((tool_call.name, fc))
                remove_now = count >= ToolCallTracker.REMOVE_THRESHOLD or fc.is_permanent
                if remove_now:
                    tools_to_remove.append(tool_call.name)
                    reason = (
                        f"permanently unavailable ({fc.value})"
                        if fc.is_permanent
                        else f"failed {count} times with identical arguments"
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"TOOL REMOVED: `{tool_call.name}` is {reason} "
                                "and has been disabled. Use a different approach."
                            ),
                        }
                    )
                elif count >= ToolCallTracker.WARN_THRESHOLD:
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"STOP: `{tool_call.name}` has failed {count} "
                                "times with the same arguments and error. Do NOT "
                                "call it again with the same arguments. Use a "
                                "different approach or provide your best answer."
                            ),
                        }
                    )
            else:
                tracker.record_success(tool_call.name, tool_call.arguments)

        disabled_tools.update(tools_to_remove)

        # Global failure budget: force final answer
        if tracker.budget_exhausted:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"You have {tracker.total_failures} failed tool calls "
                        "this turn. Stop calling tools and produce your final "
                        "answer NOW with whatever information you have."
                    ),
                }
            )
            nudged_for_final = True

        return _ToolBatchResult(
            any_failed=any_failed,
            failed_this_batch=failed_this_batch,
            nudged_for_final=nudged_for_final,
            last_tool_call_msg_idx=last_tool_call_msg_idx,
            tool_calls_this_batch=tool_calls_this_batch,
        )

    def _evaluate_progress(
        self,
        response: "LLMResponse",
        messages: list[dict],
        tracker: "ToolCallTracker",
        _tools_def_cache: list[dict],
        any_failed: bool,
        failed_this_batch: list[tuple[str, FailureClass]],
        has_plan: bool,
        turn_tool_calls: int,
        user_text: str,
        nudged_for_final: bool,
    ) -> bool:
        """Append REFLECT-phase system messages based on the current turn state.

        Mutates *messages* in-place; returns the (potentially updated)
        *nudged_for_final* flag.
        """
        had_delegations = any(tc.name in _DELEGATION_TOOL_NAMES for tc in response.tool_calls)

        if had_delegations and self._delegation_count >= self._max_delegations:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Delegation budget exhausted. You have completed all "
                        "delegated sub-tasks. Do NOT delegate any more work. "
                        "Synthesize the results you have and produce your "
                        "final answer NOW."
                    ),
                }
            )
        elif any_failed:
            _permanent = tracker.permanent_failures
            _available = [
                t["function"]["name"]
                for t in _tools_def_cache
                if t["function"]["name"] not in _permanent
            ]
            messages.append(
                {
                    "role": "system",
                    "content": _build_failure_prompt(
                        failed_this_batch,
                        _permanent,
                        _available,
                    ),
                }
            )
        elif had_delegations:
            _ungrounded = any(
                "grounded=False" in (m.get("content") or "")
                for m in messages[-len(response.tool_calls) :]
                if m.get("role") == "tool"
            )
            nudge = (
                "Delegation(s) complete. Review the results above. "
                "If all planned delegations are done, produce your "
                "final answer synthesizing the results. Do NOT start "
                "another round of delegations unless the results are "
                "clearly insufficient (e.g. empty or errored)."
            )
            if _ungrounded:
                nudge += (
                    "\n\nWARNING: One or more specialists completed their "
                    "task without using any tools. Those results may be "
                    "unverified. Consider cross-checking critical claims "
                    "before including them in your answer."
                )
            # If the agent used sequential delegate for an inherently parallel
            # request, nudge it to switch to delegate_parallel next round.
            if not any(
                tc.name == "delegate_parallel" for tc in response.tool_calls
            ) and self._has_parallel_structure(user_text):
                nudge += (
                    "\n\nYou used sequential `delegate` but the user's "
                    "request lists independent sub-tasks. For the "
                    "remaining work, switch to `delegate_parallel` "
                    "to execute them concurrently."
                )
            messages.append({"role": "system", "content": nudge})
        elif (
            has_plan
            and not had_delegations
            and turn_tool_calls >= 5
            and self._delegation_count == 0
            and self.tools.get("delegate_parallel")
        ):
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"You have executed {turn_tool_calls} tool calls "
                        "solo without delegating. STOP doing the work "
                        "yourself. Use `delegate_parallel` NOW to distribute "
                        "remaining work to specialist agents. This is "
                        "required for multi-part tasks."
                    ),
                }
            )
        elif has_plan and len(response.tool_calls) >= 1:
            messages.append(
                {
                    "role": "system",
                    "content": prompts.get("progress"),
                }
            )
        elif len(response.tool_calls) >= 3:
            messages.append(
                {
                    "role": "system",
                    "content": prompts.get("reflect"),
                }
            )

        return nudged_for_final

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: ProgressCallback | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the Plan-Act-Observe-Reflect agent loop.

        Returns (final_content, tools_used, messages).
        """
        messages = initial_messages
        self._active_messages = messages
        self._delegation_count = 0
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        turn_tool_calls = 0
        nudged_for_final = False
        consecutive_errors = 0
        has_plan = False
        plan_enforced = False
        _last_tool_call_msg_idx: int = -1  # index of last assistant msg with tool_calls
        tracker = ToolCallTracker()
        # Tools suppressed this turn due to repeated or permanent failures.
        # Stored separately from the registry so removal is scoped to this turn
        # only — the registry is never mutated, keeping tools available for
        # subsequent turns.
        disabled_tools: set[str] = set()
        # Cache tools_def between iterations; recomputed only when disabled_tools changes.
        # Eagerly built here so the first iteration has a valid (non-empty) list.
        _tools_def_snapshot: frozenset[str] = frozenset()
        _tools_def_cache: list[dict] = list(self.tools.get_definitions())

        # Reset per-turn token accumulators
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        # Reserve ~20% of context window for the model's response
        context_budget = int(self.config.context_window_tokens * _CONTEXT_RESERVE_RATIO)

        # Extract the last user message (used by planning + verification)
        user_text = ""
        for m in reversed(messages):
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

        # --- PLAN phase: inject planning prompt for complex tasks ----------
        if self.config.planning_enabled:
            if self._needs_planning(user_text):
                messages.append(
                    {
                        "role": "system",
                        "content": prompts.get("plan"),
                    }
                )
                has_plan = True
                logger.debug("Planning prompt injected for: {}...", user_text[:60])
                # Parallel structure nudge: when the request lists independent
                # subtasks, explicitly instruct parallel delegation.
                if self._has_parallel_structure(user_text):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The user's request lists multiple INDEPENDENT "
                                "sub-tasks or areas. Use `delegate_parallel` (NOT "
                                "sequential `delegate`) to fan them out concurrently. "
                                "Sequential `delegate` is only appropriate when task B "
                                "depends on task A's output."
                            ),
                        }
                    )
                    logger.debug("Parallel structure nudge injected")

        while iteration < self.max_iterations:
            iteration += 1

            # --- Context compression: keep messages within budget ----------
            # Skip the (expensive) compression pass when well under budget.
            if estimate_messages_tokens(messages) > int(context_budget * 0.85):
                summary_model = self.config.summary_model or self.model
                preserve_n = _dynamic_preserve_recent(messages, _last_tool_call_msg_idx)
                messages = await summarize_and_compress(
                    messages,
                    context_budget,
                    provider=self.provider,
                    model=summary_model,
                    tool_token_threshold=self.config.tool_result_context_tokens,
                    preserve_recent=preserve_n,
                )

            # Exclude tools disabled this turn (failure threshold or permanent failure).
            # Read after removals so the LLM never sees a tool it cannot use.
            # Recompute only when disabled_tools has changed since last iteration.
            if frozenset(disabled_tools) != _tools_def_snapshot:
                _tools_def_cache = [
                    t
                    for t in self.tools.get_definitions()
                    if t["function"]["name"] not in disabled_tools
                ]
                _tools_def_snapshot = frozenset(disabled_tools)
            tools_def = _tools_def_cache
            active_tools = tools_def if not nudged_for_final else None

            # --- LLM call (streaming when a progress callback exists) ------
            if on_progress and iteration > 1:
                # Emit "thinking" status on subsequent iterations (first is implicit from run.start)
                await on_progress("", status_code="thinking")
            response = await self._call_llm(
                messages,
                active_tools,
                on_progress,
            )
            # Accumulate token usage from this LLM call
            self._turn_llm_calls += 1
            self._turn_tokens_prompt += response.usage.get("prompt_tokens", 0)
            self._turn_tokens_completion += response.usage.get("completion_tokens", 0)

            # --- Check for LLM-level errors --------------------------------
            _err_action, consecutive_errors, _err_content = await self._handle_llm_error(
                response, consecutive_errors, messages, on_progress
            )
            if _err_action == "continue":
                continue
            if _err_action == "break":
                final_content = _err_content
                break

            consecutive_errors = 0

            # --- ACT: execute tool calls -----------------------------------
            if response.has_tool_calls:
                # Plan enforcement: if planning was requested but model jumped
                # straight to tools without producing a plan, nudge it once.
                # Delegation calls (delegate/delegate_parallel) are exempt
                # because delegation itself is a form of planning.
                is_delegation = all(tc.name in _DELEGATION_TOOL_NAMES for tc in response.tool_calls)
                if (
                    has_plan
                    and not plan_enforced
                    and turn_tool_calls == 0
                    and not response.content
                    and not is_delegation
                ):
                    plan_enforced = True
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "You were asked to produce a plan before acting. "
                                "Please outline your plan first, then proceed with tool calls."
                            ),
                        }
                    )
                    logger.debug("Plan enforcement: nudging model to produce plan first")
                    continue

                # Filter out malformed tool calls (empty name or empty arguments)
                valid_calls = [
                    tc for tc in response.tool_calls if tc.name and tc.name.strip() and tc.arguments
                ]
                skipped = len(response.tool_calls) - len(valid_calls)
                if skipped:
                    logger.warning(
                        "Filtered {} malformed tool call(s) with empty name/arguments",
                        skipped,
                    )
                if not valid_calls:
                    # All calls were malformed — treat as empty response
                    if not response.content and turn_tool_calls > 0 and not nudged_for_final:
                        nudged_for_final = True
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Your previous tool calls were malformed (empty name or "
                                    "arguments). Produce the final answer directly without "
                                    "calling any more tools."
                                ),
                            }
                        )
                        continue
                    final_content = self._strip_think(response.content)
                    messages = self.context.add_assistant_message(
                        messages,
                        final_content,
                        reasoning_content=response.reasoning_content,
                    )
                    break

                # Replace with filtered list
                response = LLMResponse(
                    content=response.content,
                    tool_calls=valid_calls,
                    finish_reason=response.finish_reason,
                    usage=response.usage,
                    reasoning_content=response.reasoning_content,
                )

                if on_progress:
                    # Note: StreamingLLMCaller already routed response.content as
                    # a status event (Option B) — do NOT re-emit here as text.
                    await on_progress("", status_code="calling_tool")
                    for tc in response.tool_calls:
                        await on_progress(
                            "",
                            tool_call={
                                "toolCallId": tc.id,
                                "toolName": tc.name,
                                "args": tc.arguments,
                            },
                        )

                # --- ACT + OBSERVE: execute tools and process results ------
                batch = await self._process_tool_results(
                    response,
                    messages,
                    tools_used,
                    disabled_tools,
                    tracker,
                    _tools_def_cache,
                    on_progress,
                    nudged_for_final,
                )
                turn_tool_calls += batch.tool_calls_this_batch
                nudged_for_final = batch.nudged_for_final
                _last_tool_call_msg_idx = batch.last_tool_call_msg_idx

                # --- REFLECT: evaluate progress and inject guidance ---------
                nudged_for_final = self._evaluate_progress(
                    response,
                    messages,
                    tracker,
                    _tools_def_cache,
                    batch.any_failed,
                    batch.failed_this_batch,
                    has_plan,
                    turn_tool_calls,
                    user_text,
                    nudged_for_final,
                )

            else:
                # --- No tool calls: the model is producing a text answer ---
                if not response.content and turn_tool_calls > 0 and not nudged_for_final:
                    nudged_for_final = True
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "You have already used tools in this turn. "
                                "Now produce the final answer summarizing the tool results. "
                                "Do not call any more tools."
                            ),
                        }
                    )
                    logger.info(
                        "Tool results present but no final text; retrying once for final answer."
                    )
                    continue
                final_content = self._strip_think(response.content)
                messages = self.context.add_assistant_message(
                    messages,
                    final_content,
                    reasoning_content=response.reasoning_content,
                )
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )
            messages = self.context.add_assistant_message(messages, final_content)

        # --- Verification pass ---------------------------------------------
        if final_content is not None:
            final_content, messages = await self._verify_answer(
                user_text,
                final_content,
                messages,
            )

        return final_content, tools_used, messages

    # ------------------------------------------------------------------
    # Self-critique / verification (Step 2)
    # ------------------------------------------------------------------

    async def _verify_answer(
        self,
        user_text: str,
        candidate: str,
        messages: list[dict],
    ) -> tuple[str, list[dict]]:
        """Run a verification pass — delegates to AnswerVerifier."""
        return await self._verifier.verify(user_text, candidate, messages)

    # ------------------------------------------------------------------
    # Reaction handling (Step 8 — Feedback loop)
    # ------------------------------------------------------------------

    async def handle_reaction(self, reaction: ReactionEvent) -> None:
        """Translate an emoji reaction from a channel into a feedback event.

        Channels can call this when a user adds a reaction to a bot message.
        The reaction is mapped to positive/negative and persisted via the
        feedback tool.
        """
        rating = reaction.rating
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
        via ``_apply_role_for_turn``.  When routing is disabled the loop
        behaves exactly as before.
        """
        self._running = True
        self._stop_event = asyncio.Event()
        await self._connect_mcp()
        self._ensure_coordinator()
        await self.context.memory.ensure_health()  # LAN-101: non-blocking vector health check

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
                            role_name, confidence = await self._coordinator.classify(msg.content)
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
                            self._record_route_trace(
                                "route",
                                role=role.name,
                                confidence=confidence,
                                latency_ms=classify_latency_ms,
                                message_excerpt=msg.content,
                            )
                            turn_ctx = self._apply_role_for_turn(role)

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

                    self._reset_role_after_turn(turn_ctx)

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
                    self._reset_role_after_turn(turn_ctx)
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

        from nanobot.agent.coordinator import Coordinator, build_default_registry

        registry = build_default_registry(self._routing_config.default_role)
        for role_cfg in self._routing_config.roles:
            registry.merge_register(role_cfg)
        self._coordinator = Coordinator(
            provider=self.provider,
            registry=registry,
            classifier_model=self._routing_config.classifier_model,
            default_role=self._routing_config.default_role,
        )
        self._dispatcher.coordinator = self._coordinator
        self.missions.coordinator = self._coordinator
        self._wire_delegate_tools()

        # Wire agent registry into the unified capability registry via public API
        self._capabilities.wire_agent_registry(registry)

        logger.info(
            "Multi-agent routing enabled with {} roles",
            len(registry),
        )

    def _wire_delegate_tools(self) -> None:
        """Set the dispatch callback and role validation on delegate tools."""
        self._dispatcher.wire_delegate_tools(
            available_roles_fn=self._capabilities.role_names,
        )

    def _record_route_trace(self, event: str, **kwargs: Any) -> None:
        """Forward to dispatcher."""
        self._dispatcher.record_route_trace(event, **kwargs)

    def get_routing_trace(self) -> list[dict[str, Any]]:
        """Return a copy of the routing trace."""
        return self._dispatcher.get_routing_trace()

    def _gather_recent_tool_results(self, max_results: int = 15, max_chars: int = 8000) -> str:
        return self._dispatcher.gather_recent_tool_results(max_results, max_chars)

    async def _dispatch_delegation(
        self,
        target_role: str,
        task: str,
        context: str | None,
    ) -> DelegationResult:
        return await self._dispatcher.dispatch(target_role, task, context)

    @staticmethod
    def _classify_task_type(role: str, task: str) -> str:
        return DelegationDispatcher.classify_task_type(role, task)

    def _extract_plan_text(self) -> str:
        return self._dispatcher.extract_plan_text()

    def _extract_user_request(self) -> str:
        return self._dispatcher.extract_user_request()

    def _build_execution_context(self, task_type: str) -> str:
        return self._dispatcher.build_execution_context(task_type)

    def _build_parallel_work_summary(self, role: str) -> str:
        return self._dispatcher.build_parallel_work_summary(role)

    def _build_delegation_contract(
        self,
        role: str,
        task: str,
        context: str | None,
        task_type: str,
    ) -> tuple[str, str]:
        return self._dispatcher.build_delegation_contract(role, task, context, task_type)

    async def _execute_delegated_agent(
        self,
        role: AgentRoleConfig,
        task: str,
        context: str | None,
    ) -> tuple[str, list[str]]:
        return await self._dispatcher.execute_delegated_agent(role, task, context)

    # ------------------------------------------------------------------
    # Per-turn role switching (multi-agent routing)
    # ------------------------------------------------------------------

    def _apply_role_for_turn(self, role: AgentRoleConfig) -> TurnContext:
        """Temporarily override agent settings for the current turn.

        Returns a ``TurnContext`` snapshot that must be passed to
        ``_reset_role_after_turn`` to restore the original configuration.
        """
        # Only copy the tool registry when filtering will actually be applied.
        # Roles with no allowed/denied lists leave the registry unchanged, so
        # copying is wasted allocation.
        _will_filter = role.allowed_tools is not None or bool(role.denied_tools)
        ctx = TurnContext(
            model=self.model,
            temperature=self.temperature,
            max_iterations=self.max_iterations,
            role_prompt=self.context.role_system_prompt,
            tools=self.tools.snapshot() if _will_filter else None,
        )

        if role.model:
            self.model = role.model
        if role.temperature is not None:
            self.temperature = role.temperature
        if role.max_iterations is not None:
            self.max_iterations = role.max_iterations
        self.context.role_system_prompt = role.system_prompt or ""
        self.role_name = role.name

        # Apply role-specific tool filtering
        self._filter_tools_for_role(role)
        logger.debug("Applied role '{}' for turn (model={})", role.name, self.model)
        return ctx

    def _filter_tools_for_role(self, role: AgentRoleConfig) -> None:
        """Remove tools that the role's allowed/denied lists exclude."""
        allowed = set(role.allowed_tools) if role.allowed_tools is not None else None
        denied = set(role.denied_tools) if role.denied_tools else set()
        if allowed is None and not denied:
            return
        for name in list(self.tools.tool_names):
            if allowed is not None and name not in allowed:
                self.tools.unregister(name)
            elif name in denied:
                self.tools.unregister(name)

    def _reset_role_after_turn(self, ctx: TurnContext | None) -> None:
        """Restore original agent settings after a routed turn.

        ``ctx`` is the ``TurnContext`` returned by ``_apply_role_for_turn``.
        Passing ``None`` is a no-op (safe to call when no role was applied).
        """
        if ctx is None:
            return
        self.model = ctx.model
        self.temperature = ctx.temperature
        self.max_iterations = ctx.max_iterations
        self.context.role_system_prompt = ctx.role_prompt
        self.role_name = self.role_config.name if self.role_config else ""
        # Restore full tool set (only non-None — None means no filtering was applied)
        if ctx.tools is not None:
            self.tools.restore(ctx.tools)

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

    def _get_consolidation_lock(self, session_key: str) -> asyncio.Lock:
        return self._consolidator.get_lock(session_key)

    def _prune_consolidation_lock(self, session_key: str, lock: asyncio.Lock) -> None:
        """Drop lock entry if no longer in use."""
        self._consolidator.prune_lock(session_key, lock)

    async def _run_consolidation_task(self, session: Session, lock: asyncio.Lock) -> None:
        """Run one consolidation pass; holds the semaphore and per-session lock."""
        try:
            async with self._consolidation_sem:
                async with lock:
                    await self._consolidate_memory(session)
        finally:
            self._consolidating.discard(session.key)
            self._prune_consolidation_lock(session.key, lock)

    def _should_force_verification(self, text: str) -> bool:
        return self._verifier.should_force_verification(text)

    async def _attempt_recovery(
        self,
        msg: InboundMessage,
        all_msgs: list[dict[str, Any]],
    ) -> str | None:
        """Try a single recovery LLM call with minimal context when the main loop produced None.

        Uses only the system prompt and the original user message (no tool history)
        with tools disabled to force a direct text answer.
        """
        # Extract the system prompt and the last user message from the conversation.
        system_msg = next((m for m in all_msgs if m.get("role") == "system"), None)
        user_msg = None
        for m in reversed(all_msgs):
            if m.get("role") == "user":
                user_msg = m
                break

        if not system_msg or not user_msg:
            logger.warning("Recovery skipped: missing system or user message")
            return None

        recovery_messages = [
            system_msg,
            user_msg,
            {
                "role": "system",
                "content": (
                    "Your previous attempt to answer did not produce a response. "
                    "Answer the user's message directly without calling any tools. "
                    "If you truly cannot answer, say what you know and suggest next steps."
                ),
            },
        ]

        logger.info("Attempting recovery LLM call for {}:{}", msg.channel, msg.chat_id)
        try:
            response = await self.provider.chat(
                messages=recovery_messages,
                tools=None,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.config.max_tokens,
            )
        except Exception:  # crash-barrier: recovery LLM call
            logger.exception("Recovery LLM call failed")
            return None

        if response.finish_reason == "error":
            logger.warning("Recovery LLM call returned error: {}", response.content)
            return None

        content = self._strip_think(response.content)
        if content:
            logger.info("Recovery succeeded, returning answer")
        else:
            logger.warning("Recovery LLM call produced no usable content")
        return content

    @staticmethod
    def _build_no_answer_explanation(user_text: str, messages: list[dict[str, Any]]) -> str:
        """Explain why the agent could not produce an answer on this turn."""
        tool_results = [m for m in messages if m.get("role") == "tool"]
        last_tool = tool_results[-1] if tool_results else None
        last_tool_name = str(last_tool.get("name", "")) if last_tool else ""
        last_tool_content = str(last_tool.get("content", "")) if last_tool else ""
        lowered = last_tool_content.lower()

        reasons: list[str] = []
        if not tool_results:
            reasons.append("The model did not produce a response for this message.")
        if "exit code: 1" in lowered or "no such file" in lowered or "not found" in lowered:
            reasons.append(
                f"My last check with `{last_tool_name or 'a tool'}` returned no matching data."
            )
        if "permission denied" in lowered:
            reasons.append("The lookup failed due to a local permission error.")
        if "insufficient_quota" in lowered or "429" in lowered:
            reasons.append("A provider quota/rate limit blocked part of the retrieval.")
        if not reasons:
            reasons.append("The model returned no final answer text after tool execution.")

        question = (user_text or "").strip()
        _question_words = {"who", "what", "when", "where", "why", "how", "is", "are", "can", "do"}
        looks_like_question = "?" in question or (
            question.split()[0].lower() in _question_words if question else False
        )
        help_line = (
            "Please try rephrasing your question or asking again."
            if looks_like_question
            else "Please share the fact directly and I can save it to memory."
        )

        primary_reason = reasons[0]
        return f"Sorry, I couldn't answer that just now. {primary_reason} {help_line}"

    def _make_bus_progress(
        self,
        channel: str,
        chat_id: str,
        base_meta: dict,
        canonical_builder: CanonicalEventBuilder,
    ) -> ProgressCallback:
        """Return a ``ProgressCallback`` that publishes structured progress events onto the bus.

        Each call shallow-copies ``base_meta``, merges per-event fields, and
        attaches the appropriate canonical event from ``canonical_builder``
        before publishing an ``OutboundMessage`` with ``_progress=True``.

        The returned coroutine captures ``channel``, ``chat_id``, ``base_meta``,
        and ``canonical_builder`` by value so it remains valid for the full turn
        even if the caller rebinds its local variables.
        """

        async def _progress(
            content: str,
            *,
            tool_hint: bool = False,
            streaming: bool = False,
            tool_call: dict | None = None,
            tool_result: dict | None = None,
            delegate_start: dict | None = None,
            delegate_end: dict | None = None,
            status_code: str = "",
            status_label: str = "",
        ) -> None:
            meta = dict(base_meta)
            meta["_tool_hint"] = tool_hint
            meta["_streaming"] = streaming
            if tool_call:
                meta["_tool_call"] = tool_call
                meta["_canonical"] = canonical_builder.tool_call(
                    tool_call_id=tool_call["toolCallId"],
                    tool_name=tool_call["toolName"],
                    args=tool_call.get("args", {}),
                )
            elif tool_result:
                meta["_tool_result"] = tool_result
                meta["_canonical"] = canonical_builder.tool_result(
                    tool_call_id=tool_result["toolCallId"],
                    tool_name=tool_result.get("toolName", ""),
                    result=tool_result.get("result", ""),
                )
            elif delegate_start:
                meta["_canonical"] = canonical_builder.delegate_start(
                    delegation_id=delegate_start["delegation_id"],
                    child_role=delegate_start["child_role"],
                    task_title=delegate_start.get("task_title", ""),
                )
            elif delegate_end:
                meta["_canonical"] = canonical_builder.delegate_end(
                    delegation_id=delegate_end["delegation_id"],
                    success=delegate_end.get("success", True),
                )
            elif status_code:
                meta["_canonical"] = canonical_builder.status(status_code, label=status_label)
            elif content:
                # on_progress always delivers cumulative text (the full text
                # assembled so far), regardless of the streaming flag.
                # text_flush() deduplicates against what was already sent.
                meta["_canonical"] = canonical_builder.text_flush(content)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        return _progress  # type: ignore[return-value]

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
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
            final_content, _, all_msgs = await self._run_agent_loop(messages)
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
            lock = self._get_consolidation_lock(session.key)
            self._consolidating.add(session.key)
            try:
                async with lock:
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
            finally:
                self._consolidating.discard(session.key)
                self._prune_consolidation_lock(session.key, lock)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content="New session started."
            )
        if cmd == "/help":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="🐈 nanobot commands:\n/new — Start a new conversation\n/help — Show available commands",
            )

        memory_store = self.context.memory

        # Run both memory pre-checks in a single thread dispatch to avoid
        # two round-trips through asyncio.to_thread for what are in-memory ops.
        # handle_user_conflict_reply short-circuits when message is a conflict
        # resolution; apply_live_user_correction extracts preference/fact edits.
        _channel = msg.channel
        _chat_id = msg.chat_id
        _content = msg.content
        _enable_cc = self.config.memory_enable_contradiction_check

        def _pre_turn_memory() -> tuple[dict[str, Any], dict[str, Any] | None]:
            cr = memory_store.handle_user_conflict_reply(_content)
            if cr.get("handled"):
                return cr, None
            try:
                corr = memory_store.apply_live_user_correction(
                    _content,
                    channel=_channel,
                    chat_id=_chat_id,
                    enable_contradiction_check=_enable_cc,
                )
            except (RuntimeError, KeyError, TypeError):
                logger.exception("Live correction capture failed")
                corr = {}
            return cr, corr

        conflict_reply, correction_result = await asyncio.to_thread(_pre_turn_memory)
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

        # Defer conflict questions until after the agent answers the user's message.
        # We check here and append to the response later instead of blocking.
        pending_conflict_question = memory_store.ask_user_for_conflict(
            user_message=msg.content,
        )

        unconsolidated = len(session.messages) - session.last_consolidated
        if (
            self.config.memory_enabled
            and unconsolidated >= self.config.memory_window
            and session.key not in self._consolidating
        ):
            self._consolidating.add(session.key)
            lock = self._get_consolidation_lock(session.key)
            _task = asyncio.create_task(self._run_consolidation_task(session, lock))
            self._consolidation_tasks.add(_task)
            _task.add_done_callback(self._consolidation_tasks.discard)
            _task.add_done_callback(
                lambda t: (
                    logger.exception("Consolidation task failed")
                    if not t.cancelled() and t.exception()
                    else None
                )
            )

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        self._ensure_scratchpad(key)
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=self.config.memory_window)
        verify_before_answer = self._should_force_verification(msg.content)
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

        # Build a canonical event builder scoped to this request.
        # turn_id is derived from the number of complete turns already in session.
        _turn_num = len(session.messages) // 2
        _canonical_message_id = "msg_asst_" + uuid.uuid4().hex[:12]
        _canonical_builder = CanonicalEventBuilder(
            run_id=TraceContext.get()["request_id"] or key,
            session_id=key,
            turn_id=f"turn_{_turn_num:05d}",
            actor_id=self.role_name,
        )

        # Build a base metadata dict once for this turn; per-event fields are
        # shallow-merged on each call to avoid re-copying msg.metadata each time.
        _base_meta: dict = dict(msg.metadata or {})
        _base_meta["_progress"] = True

        _bus_progress = self._make_bus_progress(
            msg.channel, msg.chat_id, _base_meta, _canonical_builder
        )

        # Emit run.start + message.start before the agent loop begins.
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
        # so delegation lifecycle events surface to the web stream.
        self._dispatcher.on_progress = _bus_progress

        final_content, tools_used, all_msgs = await self._run_agent_loop(
            initial_messages,
            # External on_progress (e.g. _cli_progress) may only implement the
            # simplified (content: str) signature; ProgressCallback is the full
            # internal signature. BP-M2: tracked for a future wrapper.
            on_progress=(on_progress or _bus_progress) if self.config.streaming_enabled else None,  # type: ignore[arg-type]
        )

        # Clear the per-turn callback to prevent cross-turn leakage.
        self._dispatcher.on_progress = None

        if final_content is None:
            final_content = await self._attempt_recovery(msg, all_msgs)

        if final_content is None:
            final_content = self._build_no_answer_explanation(msg.content, all_msgs)
            # Ensure fallback responses are recorded in the session log.
            all_msgs = self.context.add_assistant_message(all_msgs, final_content)

        # Annotate the active langfuse span with request metadata + output.
        # Token counts are intentionally omitted — the authoritative values
        # are on the child GENERATION observations emitted by litellm's OTEL
        # callback.  Duplicating them here with our internal streaming counter
        # creates a confusing discrepancy (the streaming counter under-counts
        # when the provider applies prompt-caching or tool-token adjustments).
        update_current_span(
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

        # --- Request audit line ---
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

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

        # Append deferred conflict question after answering the user's message.
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
        # message.end carries the authoritative usage and signals the end of the
        # assistant turn. SSE projection treats message.end the same as run.end.
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
        """Delegate to ConsolidationOrchestrator."""
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
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        self._ensure_coordinator()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
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
            response = await self._process_message(
                msg, session_key=session_key, on_progress=on_progress
            )
        return response.content if response else ""
