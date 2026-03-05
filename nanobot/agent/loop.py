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
import re
from contextlib import AsyncExitStack
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import (
    ContextBuilder,
    summarize_and_compress,
)
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.feedback import FeedbackTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage, ReactionEvent
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig
    from nanobot.cron.service import CronService


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
    ):
        from nanobot.config.schema import ExecToolConfig

        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.config = config
        self.workspace = config.workspace_path
        self.model = config.model or provider.get_default_model()
        self.max_iterations = config.max_iterations
        self.temperature = config.temperature
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
        }
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = config.restrict_to_workspace

        self.context = ContextBuilder(
            self.workspace,
            memory_retrieval_k=self.memory_retrieval_k,
            memory_token_budget=self.memory_token_budget,
            memory_md_token_cap=config.memory_md_token_cap,
            memory_rollout_overrides=self.memory_rollout_overrides,
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

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                shell_mode=self.config.shell_mode,
            )
        )
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        self.tools.register(
            FeedbackTool(
                events_file=self.workspace / "memory" / "events.jsonl",
            )
        )
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

        # Skill-provided custom tools (Step 14)
        for tool in self.context.skills.discover_tools():
            self.tools.register(tool)

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

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        clean = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
        if not clean:
            return None
        # Strip common reasoning prefixes that sometimes leak into final answers.
        # Remove leading lines like "analysis", "assistantanalysis", etc.
        while True:
            stripped = re.sub(
                r"^(assistant\s*)?analysis\b[^\n]*\n?", "", clean, flags=re.IGNORECASE
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
        "Keep each step to one sentence. Then begin executing step 1."
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

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the Plan-Act-Observe-Reflect agent loop.

        Returns (final_content, tools_used, messages).
        """
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        turn_tool_calls = 0
        nudged_for_final = False
        consecutive_errors = 0
        has_plan = False

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

        while iteration < self.max_iterations:
            iteration += 1

            # --- Context compression: keep messages within budget ----------
            summary_model = self.config.summary_model or self.model
            messages = await summarize_and_compress(
                messages,
                context_budget,
                provider=self.provider,
                model=summary_model,
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
            consecutive_errors = 0

            # --- ACT: execute tool calls -----------------------------------
            if response.has_tool_calls:
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
                if any_failed:
                    # Failure-aware: prompt alternative strategy
                    messages.append(
                        {
                            "role": "system",
                            "content": self._FAILURE_STRATEGY_PROMPT,
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
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
                try:
                    response = await self._process_message(msg)
                    if response is not None:
                        await self.bus.publish_outbound(response)
                    elif msg.channel in {"cli", "telegram"}:
                        # Emit an empty outbound to let channel-side state (e.g. Telegram typing indicator)
                        # flush even when the assistant only used tool-driven delivery in this turn.
                        await self.bus.publish_outbound(
                            OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content="",
                                metadata=msg.metadata or {},
                            )
                        )
                except Exception as e:
                    logger.error("Error processing message: {}", e)
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=f"Sorry, I encountered an error: {str(e)}",
                        )
                    )
            except asyncio.TimeoutError:
                continue

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
            reasons.append("I did not get usable evidence from tools or memory retrieval.")
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
        help_line = (
            "Please share the fact directly and I can save it to memory."
            if question
            else "Please restate your question and I will retry with explicit verification."
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

    _TOOL_RESULT_MAX_CHARS = 500

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime

        for m in messages[skip:]:
            entry = {k: v for k, v in m.items() if k != "reasoning_content"}
            if entry.get("role") == "tool" and isinstance(entry.get("content"), str):
                content = entry["content"]
                if len(content) > self._TOOL_RESULT_MAX_CHARS:
                    entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
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
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""
