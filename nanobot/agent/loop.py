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
import contextvars
import json
import re
import time
from contextlib import AsyncExitStack
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import (
    ContextBuilder,
    summarize_and_compress,
)
from nanobot.agent.metrics import (
    DELEGATION_LATENCY_MAX_MS,
    DELEGATION_LATENCY_SUM_MS,
    ROUTING_CLASSIFICATIONS,
    ROUTING_CLASSIFY_LATENCY_MAX_MS,
    ROUTING_CLASSIFY_LATENCY_SUM_MS,
    ROUTING_CYCLES_BLOCKED,
    ROUTING_DELEGATIONS,
    MetricsCollector,
    role_invocations_key,
    role_tool_calls_key,
)
from nanobot.agent.scratchpad import Scratchpad
from nanobot.agent.subagent import SubagentManager, run_tool_loop
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.delegate import DelegateParallelTool, DelegateTool, _CycleError
from nanobot.agent.tools.feedback import FeedbackTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.scratchpad import ScratchpadReadTool, ScratchpadWriteTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage, ReactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig, AgentRoleConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.agent.coordinator import Coordinator
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig, RoutingConfig
    from nanobot.cron.service import CronService


# Per-coroutine delegation ancestry — isolated across asyncio.gather branches.
# Each parallel delegation branch inherits the parent's ancestry snapshot;
# mutations in one branch never leak to siblings.
_delegation_ancestry: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "_delegation_ancestry", default=()
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
        }
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = config.restrict_to_workspace
        self.message_timeout = config.message_timeout

        self.context = ContextBuilder(
            self.workspace,
            memory_retrieval_k=self.memory_retrieval_k,
            memory_token_budget=self.memory_token_budget,
            memory_md_token_cap=config.memory_md_token_cap,
            memory_rollout_overrides=self.memory_rollout_overrides,
            role_system_prompt=role_config.system_prompt if role_config else "",
        )
        self.sessions = session_manager or SessionManager(self.workspace)
        self.tools = ToolRegistry()
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
        self._consolidation_locks: dict[str, asyncio.Lock] = {}
        self._register_default_tools()

        # Multi-agent coordinator (initialized lazily in run() if routing enabled)
        self._routing_config = routing_config
        self._coordinator: Coordinator | None = None

        # Delegation tracking
        self._delegation_stack: list[str] = []
        self._routing_trace: list[dict[str, Any]] = []
        self._scratchpad: Scratchpad | None = None
        self._delegation_count: int = 0
        self._max_delegations: int = 8

        # Routing metrics (lazy: only created when routing is enabled)
        self._routing_metrics: MetricsCollector | None = None
        self._trace_path = self.workspace / "memory" / "routing_trace.jsonl"

        # Reference to the current loop's message list (for delegation context)
        self._active_messages: list[dict[str, Any]] | None = None

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
        for skill_tool in self.context.skills.discover_tools():
            self.tools.register(skill_tool)

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
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

        # Update scratchpad tool references
        write_tool = self.tools.get("write_scratchpad")
        if isinstance(write_tool, ScratchpadWriteTool):
            write_tool._scratchpad = self._scratchpad
        read_tool = self.tools.get("read_scratchpad")
        if isinstance(read_tool, ScratchpadReadTool):
            read_tool._scratchpad = self._scratchpad

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        clean = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
        if not clean:
            logger.warning(
                "_strip_think removed all content from non-empty response (first 100 chars): {}",
                text[:100],
            )
            return None
        # Strip common reasoning prefixes that sometimes leak into final answers.
        # Remove leading lines like "analysis", "assistantanalysis", "analysisUser", etc.
        while True:
            stripped = re.sub(
                r"^(assistant\s*)?analysis[^\n]*\n?", "", clean, flags=re.IGNORECASE
            ).lstrip()
            if stripped == clean:
                break
            clean = stripped
        return clean or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""

        def _fmt(tc):
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'

        return ", ".join(_fmt(tc) for tc in tool_calls)

    # ------------------------------------------------------------------
    # Parallel tool execution
    # ------------------------------------------------------------------

    async def _execute_tools_parallel(
        self,
        tool_calls: list,
    ) -> list[ToolResult]:
        """Execute tool calls, running read-only tools concurrently.

        Write-capable tool calls are executed sequentially to preserve
        ordering semantics.  Read-only tools that appear *between* writes
        are batched and awaited together.
        """
        results: list[ToolResult] = [ToolResult.ok("")] * len(tool_calls)

        # Partition into sequential groups: consecutive readonly calls
        # form a parallel batch; everything else is sequential.
        i = 0
        while i < len(tool_calls):
            tc = tool_calls[i]
            tool_obj = self.tools.get(tc.name)
            is_readonly = tool_obj.readonly if tool_obj else False

            if is_readonly:
                # Collect consecutive readonly calls
                batch_start = i
                while i < len(tool_calls):
                    t = self.tools.get(tool_calls[i].name)
                    if t and t.readonly:
                        i += 1
                    else:
                        break
                batch = tool_calls[batch_start:i]
                coros = [self.tools.execute(t.name, t.arguments) for t in batch]
                batch_results = await asyncio.gather(*coros, return_exceptions=True)
                for j, br in enumerate(batch_results):
                    if isinstance(br, BaseException):
                        results[batch_start + j] = ToolResult.fail(f"Error: {br}")
                    else:
                        results[batch_start + j] = br
            else:
                results[i] = await self.tools.execute(tc.name, tc.arguments)
                i += 1

        return results

    # ------------------------------------------------------------------
    # LLM call with optional streaming (Step 15)
    # ------------------------------------------------------------------

    _STREAM_FLUSH_INTERVAL = 12  # flush partial content every N chunks

    async def _call_llm(
        self,
        messages: list[dict],
        tools: list[dict[str, Any]] | None,
        on_progress: Callable[..., Awaitable[None]] | None,
    ) -> LLMResponse:
        """Call the LLM, streaming when *on_progress* is available.

        When streaming, partial content is periodically forwarded to
        *on_progress* so that channels supporting message editing can
        show tokens incrementally.  The final :class:`LLMResponse` is
        assembled from the accumulated chunks.
        """
        # Fall back to non-streaming when there's no progress callback
        if on_progress is None:
            return await self.provider.chat(
                messages=messages,
                tools=tools,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls = []
        finish_reason = "stop"
        usage: dict[str, int] = {}
        chunk_count = 0
        last_flushed = 0

        async for chunk in self.provider.stream_chat(
            messages=messages,
            tools=tools,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        ):
            if chunk.content_delta:
                content_parts.append(chunk.content_delta)
            if chunk.reasoning_delta:
                reasoning_parts.append(chunk.reasoning_delta)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.usage:
                usage = chunk.usage
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls

            chunk_count += 1

            # Periodically flush accumulated content to the channel
            chars_since = sum(len(p) for p in content_parts[last_flushed:])
            if (
                chars_since >= 80
                and chunk_count % self._STREAM_FLUSH_INTERVAL == 0
                and not chunk.done
            ):
                partial = "".join(content_parts)
                clean = self._strip_think(partial)
                if clean:
                    await on_progress(clean, streaming=True)
                last_flushed = len(content_parts)

        full_content = "".join(content_parts) or None
        full_reasoning = "".join(reasoning_parts) or None

        return LLMResponse(
            content=full_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content=full_reasoning,
        )

    # ------------------------------------------------------------------
    # Agent loop (Plan → Act → Observe → Reflect)
    # ------------------------------------------------------------------
    # Planning & Reflection prompts
    # ------------------------------------------------------------------

    _PLAN_PROMPT = (
        "Before taking action, briefly outline a numbered plan (3-7 steps) "
        "for how you will accomplish the user's request using available tools. "
        "Keep each step to one sentence. Then begin executing step 1.\n\n"
        "DELEGATION: For tasks with multiple distinct work streams (e.g. code analysis "
        "+ architecture review + report writing), use the `delegate_parallel` tool to "
        "farm out sub-tasks to specialist agents (code, research, writing, pm) who work "
        "concurrently. Then synthesise their results. Prefer delegation over doing "
        "everything yourself when the request spans multiple domains.\n\n"
        "TWO-PHASE RULE: Always separate data-gathering from synthesis.\n"
        "  Phase 1 — Gather: use `delegate_parallel` for investigation tasks "
        "(code analysis, research, architecture review). These agents write findings "
        "to the scratchpad.\n"
        "  Phase 2 — Synthesise: AFTER Phase 1 results return, compile/synthesise "
        "yourself or delegate to a writing agent as a SEPARATE step.\n"
        "  NEVER include synthesis/writing tasks in the same `delegate_parallel` call "
        "as gathering tasks — the synthesis agent would run before data is available."
    )

    _PROGRESS_PROMPT = (
        "Briefly reflect on progress: which steps of your plan are complete, "
        "which remain? Did the tool results achieve the current step's goal? "
        "If not, adjust your plan. If all steps are done, produce the final answer."
    )

    _FAILURE_STRATEGY_PROMPT = (
        "The previous tool call failed. Before retrying:\n"
        "1. Analyze what went wrong.\n"
        "2. Propose an alternative approach.\n"
        "3. Execute the alternative, or skip this step if it's non-essential."
    )

    _REFLECT_PROMPT = (
        "Briefly reflect: did the tool results above achieve your goal? "
        "If not, state what went wrong and what you will try next. "
        "If yes, produce the final answer for the user."
    )

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
        """Detect enumerated independent subtasks in the user message.

        Looks for structural patterns (not domain-specific keywords) that
        indicate the request lists multiple independent areas of work.
        """
        import re

        text_lower = text.strip().lower()
        # Pattern 1: explicit count words ("three areas", "four parts", etc.)
        count_words = re.search(
            r"\b(two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
            r"(areas?|parts?|aspects?|sections?|components?|topics?|items?|tasks?"
            r"|dimensions?|categories?|modules?|files?|layers?)",
            text_lower,
        )
        if count_words:
            return True
        # Pattern 2: "X, Y, and Z" enumeration (3+ items separated by commas + 'and')
        enum_pattern = re.search(
            r"(?:[^,]+,\s*){2,}(?:and|&)\s+[^,.]+", text_lower
        )
        if enum_pattern:
            return True
        # Pattern 3: colon-introduced list with 3+ comma-separated items
        colon_list = re.search(r":\s*[^,]+(?:,\s*[^,]+){2,}", text_lower)
        if colon_list:
            return True
        # Pattern 4: numbered inline list ("1) X 2) Y 3) Z" or "(a) X (b) Y (c) Z")
        numbered = re.findall(r"(?:^|\s)(?:\d+[.)\]]|[a-z][.)\]])\s", text_lower)
        if len(numbered) >= 3:
            return True
        # Pattern 5: "across ... , ... , and ..." spanning pattern
        across_pattern = re.search(
            r"\bacross\b.+,.+(?:,|and)\s+", text_lower
        )
        if across_pattern:
            return True
        return False

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
                        "content": self._PLAN_PROMPT,
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
            )

            tools_def = self.tools.get_definitions()
            active_tools = tools_def if not nudged_for_final else None

            # --- LLM call (streaming when a progress callback exists) ------
            response = await self._call_llm(
                messages,
                active_tools,
                on_progress,
            )

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
                logger.warning(
                    "Content filter triggered (attempt {})", consecutive_errors
                )
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
                is_delegation = all(
                    tc.name in _delegation_names for tc in response.tool_calls
                )
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
                    tc for tc in response.tool_calls
                    if tc.name and tc.name.strip() and tc.arguments
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
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

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
                tool_results = await self._execute_tools_parallel(response.tool_calls)

                any_failed = False
                for tool_call, result in zip(response.tool_calls, tool_results):
                    turn_tool_calls += 1
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    status = "OK" if result.success else "FAIL"
                    logger.info("Tool {}: {}({})", status, tool_call.name, args_str[:200])
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result.to_llm_string()
                    )
                    if not result.success:
                        any_failed = True

                # --- REFLECT: after tool execution, evaluate progress ------
                # Check if delegation budget is exhausted
                _del_names = {"delegate", "delegate_parallel"}
                had_delegations = any(
                    tc.name in _del_names for tc in response.tool_calls
                )
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
                            "content": self._FAILURE_STRATEGY_PROMPT,
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
                    and not any(
                        tc.name == "delegate_parallel"
                        for tc in response.tool_calls
                    )
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
                            "content": self._PROGRESS_PROMPT,
                        }
                    )
                elif len(response.tool_calls) >= 3:
                    # Fallback: general reflection for many concurrent calls
                    messages.append(
                        {
                            "role": "system",
                            "content": self._REFLECT_PROMPT,
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

    _CRITIQUE_SYSTEM_PROMPT = (
        "You are a fact-checker reviewing an AI assistant's answer. "
        "Given the user's question and the assistant's candidate answer, respond with ONLY "
        "a JSON object (no markdown fencing): "
        '{"confidence": <1-5>, "issues": ["issue1", ...]}. '
        "confidence 5 = fully supported, 1 = likely wrong. "
        "List any unsupported claims, factual errors, or missing caveats in issues. "
        "If the answer is solid, return an empty issues list."
    )

    async def _verify_answer(
        self,
        user_text: str,
        candidate: str,
        messages: list[dict],
    ) -> tuple[str, list[dict]]:
        """Run a verification pass on the candidate answer.

        Returns (possibly_revised_content, updated_messages).
        If verification passes or is disabled, returns the candidate as-is.
        """
        mode = self.config.verification_mode
        if mode == "off":
            return candidate, messages

        # "on_uncertainty" — only verify questions with low memory grounding
        if mode == "on_uncertainty" and not self._should_force_verification(user_text):
            return candidate, messages

        logger.debug("Running verification pass (mode={})", mode)

        critique_messages = [
            {"role": "system", "content": self._CRITIQUE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (f"User's question: {user_text}\n\nAssistant's answer: {candidate}"),
            },
        ]

        try:
            critique_response = await self.provider.chat(
                messages=critique_messages,
                tools=None,
                model=self.model,
                temperature=0.0,
                max_tokens=512,
            )
            raw = (critique_response.content or "").strip()
            # Parse the JSON critique
            parsed = json.loads(raw)
            confidence = int(parsed.get("confidence", 5))
            issues = parsed.get("issues", [])

            if confidence >= 3 and not issues:
                logger.debug("Verification passed (confidence={})", confidence)
                return candidate, messages

            # Low confidence or issues found — retry with critique injected
            logger.info(
                "Verification flagged issues (confidence={}): {}",
                confidence,
                issues,
            )
            issue_text = "\n".join(f"- {i}" for i in issues) if issues else "Low confidence"
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"Self-check found potential issues with your answer:\n{issue_text}\n\n"
                        "Please revise your answer addressing these concerns. "
                        "If you're uncertain about a claim, say so explicitly."
                    ),
                }
            )

            # One retry pass (no tools, just revision)
            revision = await self.provider.chat(
                messages=messages,
                tools=None,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            revised = self._strip_think(revision.content) or candidate
            # Replace the last assistant message with the revised one
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "assistant":
                    messages[i]["content"] = revised
                    break
            logger.info("Answer revised after verification")
            return revised, messages

        except (json.JSONDecodeError, KeyError, ValueError):
            logger.debug("Verification response not parseable, skipping")
            return candidate, messages
        except Exception:
            logger.debug("Verification call failed, returning original answer")
            return candidate, messages

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
                try:
                    # Route through coordinator if enabled (skip system messages)
                    role_applied = False
                    if self._coordinator and msg.channel != "system":
                        t0_classify = time.monotonic()
                        role_name, confidence = await self._coordinator.classify(
                            msg.content
                        )
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
                            or AgentRoleConfig(
                                name=role_name, description="General assistant"
                            )
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
                except Exception as e:
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
        self._wire_delegate_tools()
        self._routing_metrics = MetricsCollector(
            self.workspace / "memory" / "routing_metrics.json",
            flush_interval_s=30.0,
        )
        self._routing_metrics.start()
        logger.info(
            "Multi-agent routing enabled with {} roles",
            len(registry),
        )

    def _wire_delegate_tools(self) -> None:
        """Set the dispatch callback on all registered delegate tools."""
        for name in ("delegate", "delegate_parallel"):
            tool = self.tools.get(name)
            if isinstance(tool, (DelegateTool, DelegateParallelTool)):
                tool.set_dispatch(self._dispatch_delegation)

    def _record_route_trace(
        self,
        event: str,
        *,
        role: str = "",
        confidence: float = 0.0,
        latency_ms: float = 0.0,
        from_role: str = "",
        depth: int = 0,
        success: bool = True,
        message_excerpt: str = "",
        tools_used: list[str] | None = None,
    ) -> None:
        """Append an entry to the in-memory routing trace and record metrics."""
        import json as _json

        entry: dict[str, Any] = {
            "event": event,
            "role": role,
            "confidence": confidence,
            "latency_ms": round(latency_ms, 3),
            "from_role": from_role,
            "depth": depth,
            "success": success,
            "message": message_excerpt[:80],
            "timestamp": datetime.now().isoformat(),
        }
        if tools_used is not None:
            entry["tools_used"] = tools_used
            entry["tools_used_count"] = len(tools_used)
        self._routing_trace.append(entry)

        # Persist to JSONL trace file
        try:
            self._trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self._trace_path.open("a", encoding="utf-8") as f:
                f.write(_json.dumps(entry, default=str) + "\n")
        except Exception:
            pass  # best-effort: don't break routing on I/O failure

        # Record counters
        m = self._routing_metrics
        if m is None:
            return

        if event == "route":
            m.record(ROUTING_CLASSIFICATIONS)
            m.record(ROUTING_CLASSIFY_LATENCY_SUM_MS, int(latency_ms))
            m.set_max(ROUTING_CLASSIFY_LATENCY_MAX_MS, latency_ms)
            m.record(role_invocations_key(role))
        elif event == "delegate":
            m.record(ROUTING_DELEGATIONS)
        elif event == "delegate_cycle_blocked":
            m.record(ROUTING_CYCLES_BLOCKED)
        elif event == "delegate_complete":
            m.record(DELEGATION_LATENCY_SUM_MS, int(latency_ms))
            m.set_max(DELEGATION_LATENCY_MAX_MS, latency_ms)

    def get_routing_trace(self) -> list[dict[str, Any]]:
        """Return a copy of the routing trace."""
        return list(self._routing_trace)

    def _gather_recent_tool_results(
        self, max_results: int = 15, max_chars: int = 8000
    ) -> str:
        """Extract recent tool results from the active message list for delegation context."""
        if not self._active_messages:
            return ""

        tool_results: list[str] = []
        total_chars = 0
        # Walk backwards to get the most recent results first
        for m in reversed(self._active_messages):
            if m.get("role") != "tool":
                continue
            name = m.get("name", "unknown")
            content = m.get("content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            entry = f"**{name}**: {content}"
            if total_chars + len(entry) > max_chars:
                break
            tool_results.append(entry)
            total_chars += len(entry)
            if len(tool_results) >= max_results:
                break

        if not tool_results:
            return ""
        tool_results.reverse()  # restore chronological order
        return "\n\n".join(tool_results)

    async def _dispatch_delegation(
        self,
        target_role: str,
        task: str,
        context: str | None,
    ) -> str:
        """Route a delegated sub-task through the coordinator and execute it.

        The delegation stack prevents cycles (A→B→A), while still allowing
        arbitrarily deep chains (A→B→C→…).  The delegated agent runs a
        bounded ``run_tool_loop`` from ``subagent.py``.
        """
        if not self._coordinator:
            raise RuntimeError("Coordinator not available for delegation")

        # Resolve role
        role: AgentRoleConfig | None = None
        if target_role:
            role = self._coordinator.route_direct(target_role)
        if role is None:
            role = await self._coordinator.route(task)

        # Cycle guard using per-coroutine ContextVar ancestry.
        # Each asyncio.gather branch inherits the parent's ancestry snapshot;
        # parallel siblings never see each other's mutations, so fanning out
        # the same role in parallel is safe while re-entrant chains (A→B→A)
        # are correctly blocked.
        ancestry = _delegation_ancestry.get()
        depth = len(ancestry)
        if role.name in ancestry:
            chain = " → ".join((*ancestry, role.name))
            self._record_route_trace(
                "delegate_cycle_blocked",
                role=role.name,
                from_role=ancestry[-1] if ancestry else "",
                depth=depth,
                success=False,
                message_excerpt=task,
            )
            raise _CycleError(f"Delegation cycle detected: {chain}")

        from_role = ancestry[-1] if ancestry else self.role_name
        self._record_route_trace(
            "delegate",
            role=role.name,
            from_role=from_role,
            depth=depth,
            message_excerpt=task,
        )

        t0 = time.monotonic()
        self._delegation_count += 1
        token = _delegation_ancestry.set((*ancestry, role.name))
        try:
            result, used_tools = await self._execute_delegated_agent(role, task, context)
            latency_ms = (time.monotonic() - t0) * 1000
            self._record_route_trace(
                "delegate_complete",
                role=role.name,
                latency_ms=latency_ms,
                depth=depth,
                success=True,
                message_excerpt=task,
                tools_used=used_tools,
            )
            return result
        except Exception:
            latency_ms = (time.monotonic() - t0) * 1000
            self._record_route_trace(
                "delegate_complete",
                role=role.name,
                latency_ms=latency_ms,
                depth=depth,
                success=False,
                message_excerpt=task,
            )
            raise
        finally:
            _delegation_ancestry.reset(token)

    # ------------------------------------------------------------------
    # Delegation contract construction
    # ------------------------------------------------------------------

    # Task type taxonomy: each type defines tool routing, evidence
    # expectations, completion criteria, and anti-hallucination rules.
    _TASK_TYPES: dict[str, dict[str, Any]] = {
        "local_code_analysis": {
            "prefer": ["read_file", "list_dir", "exec"],
            "avoid_first": ["web_search", "web_fetch"],
            "evidence": "file paths + code excerpts with line numbers",
            "completion": (
                "Stop when you have inspected the relevant files and can answer "
                "the question with evidence. Do not exhaustively scan every file "
                "unless the task explicitly asks for it."
            ),
            "anti_hallucination": (
                "Do not infer architecture from naming alone. "
                "Distinguish inspected evidence vs assumption. "
                "Say 'not found' when absent. Cite inspected file paths."
            ),
        },
        "repo_architecture": {
            "prefer": ["read_file", "list_dir", "exec"],
            "avoid_first": ["web_search"],
            "evidence": "file paths, module relationships, code excerpts",
            "completion": (
                "Stop when you have mapped the relevant module structure "
                "and key interfaces. Focus on structure, not every detail."
            ),
            "anti_hallucination": (
                "Only describe architecture you have verified by reading files. "
                "Do not infer from file names alone. Cite every claim."
            ),
        },
        "web_research": {
            "prefer": ["web_search", "web_fetch"],
            "avoid_first": ["exec", "write_file"],
            "evidence": "URLs, quoted excerpts, publication dates",
            "completion": (
                "Stop after finding 3-5 high-quality sources that answer "
                "the question. Cross-reference when possible."
            ),
            "anti_hallucination": (
                "Cite URLs for every claim. Distinguish search results from "
                "your own analysis. Say 'no results found' when searches fail."
            ),
        },
        "report_writing": {
            "prefer": ["write_file", "read_file"],
            "avoid_first": ["exec", "web_search"],
            "evidence": "references to source findings from other agents",
            "completion": (
                "Stop after producing the requested document. "
                "Base all content on prior agent findings."
            ),
            "anti_hallucination": (
                "Use ONLY data from prior agent findings (scratchpad). "
                "Do not invent statistics, metrics, or file paths. "
                "If data is missing, note it as a gap."
            ),
        },
        "bug_investigation": {
            "prefer": ["read_file", "exec", "list_dir"],
            "avoid_first": ["web_search", "write_file"],
            "evidence": "error messages, stack traces, file paths + line numbers",
            "completion": (
                "Stop when you have identified the root cause with evidence, "
                "or when you have exhausted reasonable investigation paths."
            ),
            "anti_hallucination": (
                "Report only errors and behavior you have observed via tools. "
                "Do not guess root causes without evidence."
            ),
        },
        "general": {
            "prefer": [],
            "avoid_first": [],
            "evidence": "tool output excerpts",
            "completion": "Stop when the task objective is met.",
            "anti_hallucination": (
                "Ground all claims in tool output. Say 'unknown' when unsure."
            ),
        },
    }

    @staticmethod
    def _classify_task_type(role: str, task: str) -> str:
        """Classify a delegation task into a task type from the taxonomy."""
        task_lower = task.lower()

        # Role-based fast paths
        if role == "writing":
            return "report_writing"

        code_signals = (
            "code", "module", "file", "function", "class", "test",
            "import", "line", "bug", "error", "refactor", "implement",
            "source", "python", ".py", "coverage", "lint", "scan",
        )
        bug_signals = ("bug", "error", "crash", "fail", "exception", "broken", "fix")
        web_signals = (
            "latest", "current", "news", "trend", "benchmark",
            "compare with", "industry", "best practice", "state of the art",
        )
        arch_signals = (
            "architecture", "subsystem", "design", "structure", "pattern",
            "how does", "relationship", "dependency",
        )
        project_signals = (
            "our", "this project", "nanobot", "workspace", "codebase",
        )

        # Bug investigation (check before general code)
        if role == "code" and any(s in task_lower for s in bug_signals):
            return "bug_investigation"

        # Architecture analysis
        if any(s in task_lower for s in arch_signals):
            return "repo_architecture"

        # Local code analysis
        if any(s in task_lower for s in code_signals) or role == "code":
            return "local_code_analysis"

        # Web research (only if no project-specific signals)
        if any(s in task_lower for s in web_signals):
            if not any(s in task_lower for s in project_signals):
                return "web_research"
            return "repo_architecture"  # project-specific → inspect locally

        # Research role defaults to repo if project-specific, web otherwise
        if role == "research":
            if any(s in task_lower for s in project_signals):
                return "repo_architecture"
            return "web_research"

        return "general"

    def _extract_plan_text(self) -> str:
        """Pull the plan from _active_messages if planning was triggered."""
        if not self._active_messages:
            return ""
        found_plan_prompt = False
        for m in self._active_messages:
            if found_plan_prompt and m.get("role") == "assistant":
                content = m.get("content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                return ""
            if (
                m.get("role") == "system"
                and isinstance(m.get("content"), str)
                and "outline a numbered plan" in m["content"]
            ):
                found_plan_prompt = True
        return ""

    def _extract_user_request(self) -> str:
        """Pull the original user message from _active_messages."""
        if not self._active_messages:
            return ""
        for m in self._active_messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str):
                    return content.strip()
        return ""

    def _build_execution_context(self, task_type: str) -> str:
        """Assemble project knowledge with tier-based stratification.

        Tier A (always): workspace root + directory layout.
        Tier C (conditional): key file excerpts — only for investigative types.
        """
        parts: list[str] = [f"Workspace: {self.workspace}"]

        # Directory tree (top-level, max 50 entries) — Tier A
        try:
            entries = sorted(self.workspace.iterdir())
            tree_lines = []
            for entry in entries[:50]:
                suffix = "/" if entry.is_dir() else ""
                tree_lines.append(f"  {entry.name}{suffix}")
            if tree_lines:
                parts.append("Directory layout:\n" + "\n".join(tree_lines))
        except OSError:
            pass

        # Tier C: key file excerpts — only for investigative task types
        if task_type in ("local_code_analysis", "repo_architecture", "bug_investigation"):
            for name in ("AGENTS.md", "README.md", "SOUL.md"):
                path = self.workspace / name
                try:
                    if path.is_file():
                        text = path.read_text(encoding="utf-8", errors="replace")[:1500]
                        if text.strip():
                            parts.append(f"--- {name} (excerpt) ---\n{text.strip()}")
                except OSError:
                    pass

        return "\n\n".join(parts)

    def _build_parallel_work_summary(self, role: str) -> str:
        """Build a brief summary of what other agents are doing (non_goals)."""
        if not self._scratchpad:
            return ""
        entries = self._scratchpad.list_entries()
        if not entries:
            return ""
        lines: list[str] = []
        for e in entries:
            if e.get("role") == role:
                continue  # skip own prior entries
            lines.append(
                f"- [{e.get('role', '?')}] {e.get('label', '')[:60]}"
            )
        return "\n".join(lines) if lines else ""

    def _build_delegation_contract(
        self,
        role: str,
        task: str,
        context: str | None,
        task_type: str,
    ) -> tuple[str, str]:
        """Build a typed delegation contract.

        Returns ``(user_content, output_schema_instruction)`` where
        output_schema_instruction is injected into the system prompt.
        """
        tt = self._TASK_TYPES.get(task_type, self._TASK_TYPES["general"])
        sections: list[str] = []

        # --- Tier A: always present ---
        # Mission
        user_request = self._extract_user_request()
        if user_request:
            sections.append(f"## Original User Request\n{user_request}")

        sections.append(f"## Your Mission\n{task}")
        if context:
            sections.append(f"### Additional Context\n{context}")

        # Project root — always prominently placed so agents know where to look
        sections.append(f"## Project Root\n`{self.workspace}`")

        # Scope & non-goals
        non_goals: list[str] = []
        avoid = tt.get("avoid_first", [])
        if avoid:
            non_goals.append(f"Do not start with: {', '.join(avoid)}")
        parallel = self._build_parallel_work_summary(role)
        if parallel:
            sections.append(
                f"## Other Agents' Work (do not duplicate)\n{parallel}"
            )
            non_goals.append("Do not duplicate work already done by other agents.")
        if non_goals:
            sections.append("## Non-Goals\n" + "\n".join(f"- {g}" for g in non_goals))

        # Tool guidance
        prefer = tt.get("prefer", [])
        tool_lines: list[str] = []
        if prefer:
            tool_lines.append(f"Preferred tools: {', '.join(prefer)}")
        if avoid:
            tool_lines.append(
                f"Avoid using first (use only if preferred tools insufficient): "
                f"{', '.join(avoid)}"
            )
        if tool_lines:
            sections.append("## Tool Guidance\n" + "\n".join(tool_lines))

        # Completion criteria
        completion = tt.get("completion", "")
        if completion:
            sections.append(f"## Completion Criteria\n{completion}")

        # Anti-hallucination constraints
        anti_h = tt.get("anti_hallucination", "")
        if anti_h:
            sections.append(f"## Evidence Rules\n{anti_h}")

        # --- Tier B: when available ---
        plan_text = self._extract_plan_text()
        if plan_text:
            sections.append(f"## Overall Plan (for context)\n{plan_text}")

        # Project context (Tier A workspace + Tier C conditional files)
        execution_ctx = self._build_execution_context(task_type)
        if execution_ctx:
            sections.append(f"## Project Context\n{execution_ctx}")

        # Tier B: parent findings (relevant prior results)
        parent_findings = self._gather_recent_tool_results()
        if parent_findings:
            sections.append(f"## Prior Results\n{parent_findings}")

        # Build the output schema instruction (goes in system prompt)
        evidence_type = tt.get("evidence", "tool output excerpts")
        output_schema = (
            "\n\nYour response MUST use this structure:\n"
            "## Findings\n<your key findings>\n\n"
            "## Evidence\n<supporting evidence: " + evidence_type + ">\n\n"
            "## Open Questions\n<anything unresolved or needing further investigation>\n\n"
            "## Confidence\n<high/medium/low with brief justification>\n\n"
            "## Files Inspected\n<list of files/sources you actually examined>"
        )

        return "\n\n".join(sections), output_schema

    async def _execute_delegated_agent(
        self,
        role: AgentRoleConfig,
        task: str,
        context: str | None,
    ) -> tuple[str, list[str]]:
        """Set up and run a delegated agent for a single sub-task.

        Returns ``(summary, tools_used)``.
        """

        # Classify task type for contract construction
        task_type = self._classify_task_type(role.name, task)
        logger.debug("Delegation task type: {} (role={})", task_type, role.name)

        # Build isolated tool set (same tools as subagent, plus delegate for chaining)
        tools = ToolRegistry()
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )
        tools.register(WebSearchTool(api_key=self.brave_api_key))
        tools.register(WebFetchTool())

        # Allow further delegation (with the shared stack for cycle detection)
        child_delegate = DelegateTool()
        child_delegate.set_dispatch(self._dispatch_delegation)
        tools.register(child_delegate)

        # Apply role-specific tool filters
        if role.denied_tools:
            for denied in role.denied_tools:
                tools.unregister(denied)
        if role.allowed_tools is not None:
            allowed = set(role.allowed_tools)
            for tname in list(tools._tools):
                if tname not in allowed:
                    tools.unregister(tname)

        # Build delegation contract
        user_content, output_schema = self._build_delegation_contract(
            role=role.name,
            task=task,
            context=context,
            task_type=task_type,
        )

        # For synthesizing roles, inject scratchpad as primary input (Tier B)
        if role.name in ("pm", "writing", "general") and self._scratchpad:
            scratchpad_content = self._scratchpad.read()
            if scratchpad_content and scratchpad_content != "Scratchpad is empty.":
                user_content += (
                    f"\n\n## Prior Agent Findings (Scratchpad)\n{scratchpad_content}"
                )

        # Build system prompt with contract-driven structure
        avail_tools = ", ".join(tools.tool_names)
        system_prompt = (
            f"You are the **{role.name}** specialist agent.\n\n"
            f"{role.system_prompt or ''}\n\n"
            f"You MUST use your available tools to complete this task. "
            f"Do NOT fabricate information — always verify with tools first."
        )
        if avail_tools:
            system_prompt += f"\nAvailable tools: {avail_tools}"
        system_prompt += output_schema

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        # Bound iterations: investigative tasks get 12, synthesis tasks get 8
        if task_type in ("report_writing", "general"):
            iter_cap = 8
        else:
            iter_cap = 12
        max_iter = min(self.max_iterations, iter_cap)
        model = role.model or self.model
        temperature = role.temperature if role.temperature is not None else self.temperature

        result, tools_used, messages = await run_tool_loop(
            provider=self.provider,
            tools=tools,
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=self.max_tokens,
            max_iterations=max_iter,
        )

        # Retry if agent didn't use any tools on an investigation-type task
        if not tools_used and task_type not in ("report_writing",) and max_iter > 2:
            logger.warning(
                "Delegated {} agent used no tools — retrying with tool-use reminder",
                role.name,
            )
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "You have not used any tools yet. You MUST use the available "
                        "tools to gather real data before producing your answer. "
                        "Start by using list_dir or read_file to inspect the workspace."
                    ),
                }
            )
            retry_result, retry_tools, _ = await run_tool_loop(
                provider=self.provider,
                tools=tools,
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=self.max_tokens,
                max_iterations=min(max_iter, 6),
            )
            if retry_tools:
                result = retry_result
                tools_used = tools_used + retry_tools

        summary = result or "No result produced."

        # Strip model artifacts: some models prefix the final response with "final"
        if summary.lower().startswith("final\n"):
            summary = summary[6:].lstrip()
        elif summary.lower().startswith("final:"):
            summary = summary[6:].lstrip()

        # Write to scratchpad if available (but return clean summary to caller)
        if self._scratchpad:
            await self._scratchpad.write(
                role=role.name,
                label=task[:80],
                content=summary,
            )

        return summary, tools_used

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
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except RuntimeError:
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None
        try:
            await self.provider.aclose()
        except Exception as e:
            logger.debug("Provider cleanup failed: {}", e)

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    def _get_consolidation_lock(self, session_key: str) -> asyncio.Lock:
        lock = self._consolidation_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._consolidation_locks[session_key] = lock
        return lock

    def _prune_consolidation_lock(self, session_key: str, lock: asyncio.Lock) -> None:
        """Drop lock entry if no longer in use."""
        if not lock.locked():
            self._consolidation_locks.pop(session_key, None)

    @staticmethod
    def _looks_like_question(text: str) -> bool:
        content = (text or "").strip().lower()
        if not content:
            return False
        if "?" in content:
            return True
        starters = (
            "what ",
            "which ",
            "who ",
            "when ",
            "where ",
            "why ",
            "how ",
            "is ",
            "are ",
            "do ",
            "does ",
            "did ",
            "can ",
            "could ",
            "should ",
            "would ",
            "will ",
        )
        return content.startswith(starters)

    def _estimate_grounding_confidence(self, query: str) -> float:
        try:
            items = self.context.memory.retrieve(
                query,
                top_k=1,
            )
        except Exception:
            return 0.0
        if not items:
            return 0.0
        top = items[0]
        try:
            score = float(top.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        return max(0.0, min(1.0, score))

    def _should_force_verification(self, text: str) -> bool:
        if not self._looks_like_question(text):
            return False
        confidence = self._estimate_grounding_confidence(text)
        return confidence < self.memory_uncertainty_threshold

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
        except Exception:
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
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

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
            except Exception:
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
        except Exception:
            logger.exception("Live correction capture failed")

        # Proactively ask for unresolved conflicts discovered during prior consolidation turns.
        pending_conflict_question = memory_store.ask_user_for_conflict()
        if pending_conflict_question:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=pending_conflict_question,
            )

        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated >= self.memory_window and session.key not in self._consolidating:
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
            on_progress=on_progress or _bus_progress,
        )

        # Track per-role tool calls
        if self._routing_metrics and tools_used and self.role_name:
            self._routing_metrics.record(
                role_tool_calls_key(self.role_name), len(tools_used)
            )

        if final_content is None:
            final_content = await self._attempt_recovery(msg, all_msgs)

        if final_content is None:
            final_content = self._build_no_answer_explanation(msg.content, all_msgs)
            # Ensure fallback responses are recorded in the session log.
            all_msgs = self.context.add_assistant_message(all_msgs, final_content)

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

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
        from datetime import datetime

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
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await self.context.memory.consolidate(
            session,
            self.provider,
            self.model,
            archive_all=archive_all,
            memory_window=self.memory_window,
            enable_contradiction_check=self.memory_enable_contradiction_check,
        )

    def _fallback_archive_snapshot(self, snapshot: list[dict]) -> bool:
        """Fallback archival used by /new when AI consolidation fails."""
        try:
            lines: list[str] = []
            for m in snapshot:
                content = m.get("content")
                if not content:
                    continue
                tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
                timestamp = str(m.get("timestamp", "?"))[:16]
                role = str(m.get("role", "unknown")).upper()
                lines.append(f"[{timestamp}] {role}{tools}: {content}")

            if not lines:
                return True

            header = (
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
                f"Fallback archive from /new ({len(lines)} messages)"
            )
            entry = header + "\n" + "\n".join(lines)
            self.context.memory.append_history(entry)
            logger.warning("/new used fallback archival: {} messages", len(lines))
            return True
        except Exception:
            logger.exception("Fallback archival failed")
            return False

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
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""
