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
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import AsyncExitStack
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.consolidation import ConsolidationOrchestrator
from nanobot.agent.context import (
    ContextBuilder,
    summarize_and_compress,
)
from nanobot.agent.delegation import DelegationDispatcher
from nanobot.agent.observability import trace_request, update_current_span
from nanobot.agent.prompt_loader import prompts
from nanobot.agent.scratchpad import Scratchpad
from nanobot.agent.streaming import StreamingLLMCaller, strip_think
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tool_executor import ToolExecutor
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.delegate import DelegateParallelTool, DelegateTool
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
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.result_cache import CacheGetSliceTool, ToolResultCache
from nanobot.agent.tools.scratchpad import ScratchpadReadTool, ScratchpadWriteTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.agent.tracing import TraceContext, bind_trace
from nanobot.agent.verifier import AnswerVerifier
from nanobot.bus.events import InboundMessage, OutboundMessage, ReactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig, AgentRoleConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.coordinator import Coordinator
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig, RoutingConfig
    from nanobot.cron.service import CronService


# Per-coroutine delegation ancestry — canonical definition in delegation.py,
# re-exported here for backward compatibility with tests.
from nanobot.agent.delegation import _delegation_ancestry  # noqa: F401


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
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
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
        from nanobot.config.schema import ExecToolConfig

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
        self.max_tokens = config.max_tokens
        self.context_window_tokens = config.context_window_tokens
        self.memory_window = config.memory_window
        self.memory_retrieval_k = config.memory_retrieval_k
        self.memory_token_budget = config.memory_token_budget
        self.memory_uncertainty_threshold = config.memory_uncertainty_threshold
        self.memory_enable_contradiction_check = config.memory_enable_contradiction_check
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
        self.restrict_to_workspace = config.restrict_to_workspace
        self.message_timeout = config.message_timeout

        self.context = ContextBuilder(
            self.workspace,
            memory_retrieval_k=self.memory_retrieval_k if config.memory_enabled else 0,
            memory_token_budget=self.memory_token_budget if config.memory_enabled else 0,
            memory_md_token_cap=config.memory_md_token_cap if config.memory_enabled else 0,
            memory_rollout_overrides=self.memory_rollout_overrides,
            role_system_prompt=role_config.system_prompt if role_config else "",
        )
        self.sessions = session_manager or SessionManager(self.workspace)
        self.tools = ToolExecutor(ToolRegistry())
        self.result_cache = ToolResultCache(workspace=self.workspace)
        self.tools._registry.set_cache(
            self.result_cache,
            provider=provider,
            summary_model=config.tool_summary_model or None,
        )
        self.subagents = SubagentManager(
            provider=provider,
            workspace=self.workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=self.restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._register_default_tools()

        # Multi-agent coordinator (initialized lazily in run() if routing enabled)
        self._routing_config = routing_config
        self._coordinator: Coordinator | None = None

        # Delegation dispatcher (owns delegation state, tracing, contracts)
        self._dispatcher = DelegationDispatcher(
            provider=provider,
            workspace=self.workspace,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_iterations=self.max_iterations,
            restrict_to_workspace=self.restrict_to_workspace,
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
            max_tokens=self.max_tokens,
        )
        self._verifier = AnswerVerifier(
            provider=provider,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            verification_mode=config.verification_mode,
            memory_uncertainty_threshold=self.memory_uncertainty_threshold,
            memory_store=self.context.memory,
        )
        self._consolidator = ConsolidationOrchestrator(self.context.memory)

        # Per-turn token accumulators (reset in _run_agent_loop)
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

    # --- Delegation state proxied to _dispatcher ---

    @property
    def _consolidation_locks(self) -> dict[str, asyncio.Lock]:
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

    def _register_default_tools(self) -> None:
        """Register the default set of tools, filtered by role config."""
        role = self.role_config
        allowed = set(role.allowed_tools) if role and role.allowed_tools is not None else None
        denied = set(role.denied_tools) if role and role.denied_tools else set()
        allowed_dir = self.workspace if self.restrict_to_workspace else None

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
            restrict_to_workspace=self.restrict_to_workspace,
            shell_mode=self.config.shell_mode,
        )
        if _should_register(exec_tool.name):
            self.tools.register(exec_tool)

        for extra_tool in (
            WebSearchTool(api_key=self.brave_api_key),
            WebFetchTool(),
            MessageTool(send_callback=self.bus.publish_outbound),
            SpawnTool(manager=self.subagents),
            FeedbackTool(events_file=self.workspace / "memory" / "events.jsonl"),
        ):
            if _should_register(extra_tool.name):
                self.tools.register(extra_tool)

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
            await connect_mcp_servers(self._mcp_servers, self.tools._registry, self._mcp_stack)
            self._mcp_connected = True
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

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.set_context(channel, chat_id, message_id)

        if spawn_tool := self.tools.get("spawn"):
            if isinstance(spawn_tool, SpawnTool):
                spawn_tool.set_context(channel, chat_id)

        if cron_tool := self.tools.get("cron"):
            if isinstance(cron_tool, CronTool):
                cron_tool.set_context(channel, chat_id)

        if feedback_tool := self.tools.get("feedback"):
            if isinstance(feedback_tool, FeedbackTool):
                feedback_tool.set_context(
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
        on_progress: Callable[..., Awaitable[None]] | None,
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
        if len(text_lower) < 20:
            return False
        # Explicit multi-step indicators
        multi_step_signals = (
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
        return any(signal in text_lower for signal in multi_step_signals)

    @staticmethod
    def _has_parallel_structure(text: str) -> bool:
        return DelegationDispatcher.has_parallel_structure(text)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
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

        # Reset per-turn token accumulators
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        # Reserve ~20% of context window for the model's response
        context_budget = int(self.context_window_tokens * 0.80)

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
            summary_model = self.config.summary_model or self.model
            messages = await summarize_and_compress(
                messages,
                context_budget,
                provider=self.provider,
                model=summary_model,
                tool_token_threshold=self.config.tool_result_context_tokens,
                preserve_recent=20,
            )

            tools_def = self.tools.get_definitions()
            active_tools = tools_def if not nudged_for_final else None

            # --- LLM call (streaming when a progress callback exists) ------
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
                    messages = self.context.add_assistant_message(messages, final_content)
                    break
                await asyncio.sleep(min(2**consecutive_errors, 10))
                continue

            if response.finish_reason == "content_filter":
                consecutive_errors += 1
                logger.warning("Content filter triggered (attempt {})", consecutive_errors)
                if consecutive_errors >= 2:
                    final_content = (
                        "The AI provider's content filter blocked my response. "
                        "Try rephrasing your question."
                    )
                    messages = self.context.add_assistant_message(messages, final_content)
                    break
                await asyncio.sleep(1)
                continue

            if response.finish_reason == "length" and not response.content:
                consecutive_errors += 1
                logger.warning(
                    "Response truncated to zero content (attempt {})", consecutive_errors
                )
                if consecutive_errors >= 2:
                    final_content = (
                        "My response was too long and got cut off. "
                        "Try asking a more specific question."
                    )
                    messages = self.context.add_assistant_message(messages, final_content)
                    break
                await asyncio.sleep(1)
                continue

            consecutive_errors = 0

            # --- ACT: execute tool calls -----------------------------------
            if response.has_tool_calls:
                # Plan enforcement: if planning was requested but model jumped
                # straight to tools without producing a plan, nudge it once.
                # Delegation calls (delegate/delegate_parallel) are exempt
                # because delegation itself is a form of planning.
                _delegation_names = {"delegate", "delegate_parallel"}
                is_delegation = all(tc.name in _delegation_names for tc in response.tool_calls)
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
                    clean = self._strip_think(response.content)
                    if clean:
                        await on_progress(clean)
                    await on_progress(
                        ToolExecutor.format_hint(response.tool_calls),
                        tool_hint=True,
                    )

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in response.tool_calls
                ]
                # Suppress draft content when tool calls are present; keep as reasoning if useful.
                reasoning = response.reasoning_content or response.content
                messages = self.context.add_assistant_message(
                    messages,
                    None,
                    tool_call_dicts,
                    reasoning_content=reasoning,
                )

                # Execute tools (parallel for readonly, sequential for writes)
                t0_tools = time.monotonic()
                tool_results = await self.tools.execute_batch(response.tool_calls)
                tools_elapsed_ms = (time.monotonic() - t0_tools) * 1000

                any_failed = False
                for tool_call, result in zip(response.tool_calls, tool_results):
                    turn_tool_calls += 1
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    status = "OK" if result.success else "FAIL"
                    bind_trace().info(
                        "tool_exec | {} | {}({}) | {:.0f}ms batch",
                        status,
                        tool_call.name,
                        args_str[:200],
                        tools_elapsed_ms,
                    )
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result.to_llm_string()
                    )
                    if not result.success:
                        any_failed = True

                # --- REFLECT: after tool execution, evaluate progress ------
                # Check if delegation budget is exhausted
                _del_names = {"delegate", "delegate_parallel"}
                had_delegations = any(tc.name in _del_names for tc in response.tool_calls)
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
                    # Failure-aware: prompt alternative strategy
                    messages.append(
                        {
                            "role": "system",
                            "content": prompts.get("failure_strategy"),
                        }
                    )
                elif had_delegations:
                    # After delegation, check if all planned work is done
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Delegation(s) complete. Review the results above. "
                                "If all planned delegations are done, produce your "
                                "final answer synthesizing the results. Do NOT start "
                                "another round of delegations unless the results are "
                                "clearly insufficient (e.g. empty or errored)."
                            ),
                        }
                    )
                elif (
                    has_plan
                    and not had_delegations
                    and turn_tool_calls >= 5
                    and self._delegation_count == 0
                    and self.tools.get("delegate_parallel")
                ):
                    # Delegation nudge: the parent is doing heavy solo work
                    # despite having delegation tools available.
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
                elif (
                    had_delegations
                    and not any(tc.name == "delegate_parallel" for tc in response.tool_calls)
                    and self._has_parallel_structure(user_text)
                ):
                    # Sequential-to-parallel correction: agent used sequential
                    # delegate but the user's request has parallel structure.
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "You used sequential `delegate` but the user's "
                                "request lists independent sub-tasks. For the "
                                "remaining work, switch to `delegate_parallel` "
                                "to execute them concurrently."
                            ),
                        }
                    )
                elif has_plan and len(response.tool_calls) >= 1:
                    # Plan-aware progress check (every tool round when planning)
                    messages.append(
                        {
                            "role": "system",
                            "content": prompts.get("progress"),
                        }
                    )
                elif len(response.tool_calls) >= 3:
                    # Fallback: general reflection for many concurrent calls
                    messages.append(
                        {
                            "role": "system",
                            "content": prompts.get("reflect"),
                        }
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
        await self._connect_mcp()
        self._ensure_coordinator()

        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
                role_applied = False
                # Set correlation IDs for this request
                TraceContext.new_request(
                    session_id=msg.session_key,
                    agent_id=self.role_name,
                )
                try:
                    # Route through coordinator if enabled (skip system messages)
                    role_applied = False
                    if self._coordinator and msg.channel != "system":
                        t0_classify = time.monotonic()
                        role_name, confidence = await self._coordinator.classify(msg.content)
                        classify_latency_ms = (time.monotonic() - t0_classify) * 1000
                        # Confidence-aware: fall back to default on low confidence
                        threshold = (
                            self._routing_config.confidence_threshold
                            if self._routing_config
                            else 0.6
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
                        self._apply_role_for_turn(role)
                        role_applied = True

                    # Wrap with timeout to prevent infinite processing
                    timeout = self.message_timeout if self.message_timeout > 0 else None
                    async with trace_request(
                        name="request",
                        input=msg.content[:200],
                        metadata={
                            "channel": msg.channel,
                            "sender": msg.sender_id,
                            "session_key": msg.session_key,
                            "model": self.model,
                            "role": self.role_name,
                        },
                    ):
                        if timeout:
                            response = await asyncio.wait_for(
                                self._process_message(msg), timeout=timeout
                            )
                        else:
                            response = await self._process_message(msg)

                    if role_applied:
                        self._reset_role_after_turn()

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
                except asyncio.TimeoutError:
                    logger.error(
                        "Message processing timed out after {}s for {}:{}",
                        self.message_timeout,
                        msg.channel,
                        msg.chat_id,
                    )
                    if role_applied:
                        self._reset_role_after_turn()
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=(
                                "Sorry, I ran out of time processing your request. "
                                "Try breaking it into smaller steps."
                            ),
                        )
                    )
                except Exception as e:  # crash-barrier: message processing
                    logger.error("Error processing message: {}", e)
                    if role_applied:
                        self._reset_role_after_turn()
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
        self._wire_delegate_tools()
        logger.info(
            "Multi-agent routing enabled with {} roles",
            len(registry),
        )

    def _wire_delegate_tools(self) -> None:
        """Set the dispatch callback on all registered delegate tools."""
        self._dispatcher.wire_delegate_tools()

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
    ) -> str:
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

    def _apply_role_for_turn(self, role: AgentRoleConfig) -> None:
        """Temporarily override agent settings for the current turn."""
        # Save originals for reset
        self._saved_model = self.model
        self._saved_temperature = self.temperature
        self._saved_max_iterations = self.max_iterations
        self._saved_role_prompt = self.context.role_system_prompt
        self._saved_tools: dict[str, Any] = dict(self.tools._tools)

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

    def _filter_tools_for_role(self, role: AgentRoleConfig) -> None:
        """Remove tools that the role's allowed/denied lists exclude."""
        allowed = set(role.allowed_tools) if role.allowed_tools is not None else None
        denied = set(role.denied_tools) if role.denied_tools else set()
        if allowed is None and not denied:
            return
        for name in list(self.tools._tools):
            if allowed is not None and name not in allowed:
                self.tools.unregister(name)
            elif name in denied:
                self.tools.unregister(name)

    def _reset_role_after_turn(self) -> None:
        """Restore original agent settings after a routed turn."""
        self.model = getattr(self, "_saved_model", self.model)
        self.temperature = getattr(self, "_saved_temperature", self.temperature)
        self.max_iterations = getattr(self, "_saved_max_iterations", self.max_iterations)
        self.context.role_system_prompt = getattr(self, "_saved_role_prompt", "")
        self.role_name = self.role_config.name if self.role_config else ""
        # Restore full tool set
        if hasattr(self, "_saved_tools"):
            self.tools._tools = self._saved_tools

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
        logger.info("Agent loop stopping")

    def _get_consolidation_lock(self, session_key: str) -> asyncio.Lock:
        return self._consolidator.get_lock(session_key)

    def _prune_consolidation_lock(self, session_key: str, lock: asyncio.Lock) -> None:
        """Drop lock entry if no longer in use."""
        self._consolidator.prune_lock(session_key, lock)

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
                max_tokens=self.max_tokens,
            )
        except Exception:  # crash-barrier: recovery LLM call
            logger.warning("Recovery LLM call failed with exception")
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
            history = session.get_history(max_messages=self.memory_window)
            skill_names = self.context.skills.detect_relevant_skills(msg.content)
            messages = self.context.build_messages(
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

        conflict_reply = memory_store.handle_user_conflict_reply(msg.content)
        if conflict_reply.get("handled"):
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=str(conflict_reply.get("message", "")),
            )

        try:
            correction_result = memory_store.apply_live_user_correction(
                msg.content,
                channel=msg.channel,
                chat_id=msg.chat_id,
                enable_contradiction_check=self.memory_enable_contradiction_check,
            )
            if correction_result.get("question"):
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=str(correction_result.get("question", "")),
                )
        except (RuntimeError, KeyError, TypeError):
            logger.exception("Live correction capture failed")

        # Defer conflict questions until after the agent answers the user's message.
        # We check here and append to the response later instead of blocking.
        pending_conflict_question = memory_store.ask_user_for_conflict(
            user_message=msg.content,
        )

        unconsolidated = len(session.messages) - session.last_consolidated
        if (
            self.config.memory_enabled
            and unconsolidated >= self.memory_window
            and session.key not in self._consolidating
        ):
            self._consolidating.add(session.key)
            lock = self._get_consolidation_lock(session.key)

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    self._prune_consolidation_lock(session.key, lock)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        self._ensure_scratchpad(key)
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=self.memory_window)
        verify_before_answer = self._should_force_verification(msg.content)
        skill_names = self.context.skills.detect_relevant_skills(msg.content)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            skill_names=skill_names,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            verify_before_answer=verify_before_answer,
        )

        async def _bus_progress(
            content: str, *, tool_hint: bool = False, streaming: bool = False
        ) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            meta["_streaming"] = streaming
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        final_content, tools_used, all_msgs = await self._run_agent_loop(
            initial_messages,
            on_progress=(on_progress or _bus_progress) if self.config.streaming_enabled else None,
        )

        # Annotate the active langfuse span with request metadata
        update_current_span(
            metadata={
                "channel": msg.channel,
                "sender": msg.sender_id,
                "model": self.model,
                "role": self.role_name,
                "session_key": key,
                "llm_calls": self._turn_llm_calls,
                "prompt_tokens": self._turn_tokens_prompt,
                "completion_tokens": self._turn_tokens_completion,
                "total_tokens": self._turn_tokens_prompt + self._turn_tokens_completion,
            },
        )

        if final_content is None:
            final_content = await self._attempt_recovery(msg, all_msgs)

        if final_content is None:
            final_content = self._build_no_answer_explanation(msg.content, all_msgs)
            # Ensure fallback responses are recorded in the session log.
            all_msgs = self.context.add_assistant_message(all_msgs, final_content)

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

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""

        max_chars = self.config.tool_result_max_chars
        for m in messages[skip:]:
            entry = {k: v for k, v in m.items() if k != "reasoning_content"}
            if entry.get("role") == "tool" and isinstance(entry.get("content"), str):
                content = entry["content"]
                if len(content) > max_chars:
                    entry["content"] = content[:max_chars] + "\n... (truncated)"
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to ConsolidationOrchestrator."""
        return await self._consolidator.consolidate(
            session,
            self.provider,
            self.model,
            memory_window=self.memory_window,
            enable_contradiction_check=self.memory_enable_contradiction_check,
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
