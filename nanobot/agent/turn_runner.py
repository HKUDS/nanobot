"""Simplified tool-use loop with guardrail checkpoints.

``TurnRunner`` replaces ``TurnOrchestrator`` as a drop-in implementation of
the ``Orchestrator`` protocol.  It inlines the tool-execution logic from
``ActPhase`` and adds guardrail checkpoints + ToolAttempt working memory.

Module boundary: this module must **never** import from ``nanobot.channels.*``,
``nanobot.bus.*``, or ``nanobot.session.*``.
"""
# size-exception: inlines ActPhase tool execution + main loop + error handler per task spec

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Literal

from loguru import logger

from nanobot.agent.callbacks import (
    ProgressCallback,
    StatusEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.agent.failure import ToolCallTracker
from nanobot.agent.streaming import StreamingLLMCaller, strip_think
from nanobot.agent.turn_guardrails import GuardrailChain
from nanobot.agent.turn_phases import (
    _ARGS_REDACT_TOOLS,
    _CONTEXT_RESERVE_RATIO,
    _dynamic_preserve_recent,
    _safe_int,
)
from nanobot.agent.turn_types import ToolAttempt, TurnResult, TurnState
from nanobot.context.compression import estimate_messages_tokens, summarize_and_compress
from nanobot.context.context import ContextBuilder
from nanobot.observability.langfuse import update_current_span
from nanobot.observability.tracing import bind_trace
from nanobot.tools.executor import ToolExecutor

if TYPE_CHECKING:
    from nanobot.config.agent import AgentConfig
    from nanobot.providers.base import LLMProvider, LLMResponse

# Inline nudge texts (avoids PromptLoader dependency)
_NUDGE_FINAL = (
    "You have already used tools in this turn. Now produce the final answer "
    "summarizing the tool results. Do not call any more tools."
)
_NUDGE_MALFORMED = (
    "Your previous tool calls were malformed (empty name or arguments). "
    "Produce the final answer directly without calling any more tools."
)
_EMPTY_MARKERS: frozenset[str] = frozenset(
    {"", "no matches found", "no results", "none", "no output"}
)


def _is_output_empty(output: str) -> bool:
    return output.strip().lower() in _EMPTY_MARKERS


class TurnRunner:
    """Simplified tool-use loop with guardrail checkpoints.

    Implements the ``Orchestrator`` protocol as a drop-in replacement for
    ``TurnOrchestrator``.  Inlines tool execution (no separate ActPhase)
    and adds guardrail + ToolAttempt working memory after each batch.
    """

    def __init__(
        self,
        *,
        llm_caller: StreamingLLMCaller,
        tool_executor: ToolExecutor,
        guardrails: GuardrailChain,
        context: ContextBuilder,
        config: AgentConfig,
        provider: LLMProvider | None = None,
    ) -> None:
        self._llm_caller = llm_caller
        self._tool_executor = tool_executor
        self._guardrails = guardrails
        self._context = context
        self._config = config
        self._provider = provider
        self._max_iterations: int = config.max_iterations
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

    # ------------------------------------------------------------------
    # Public API (satisfies Orchestrator protocol)
    # ------------------------------------------------------------------

    async def run(
        self,
        state: TurnState,
        on_progress: ProgressCallback | None,
    ) -> TurnResult:
        """Execute one full turn of the tool-use loop."""
        final_content: str | None = None
        tools_used: list[str] = []
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        _raw_cw = getattr(self._config, "context_window_tokens", 0)
        context_window = _raw_cw if isinstance(_raw_cw, int | float) else 0
        ctx_budget = int(context_window * _CONTEXT_RESERVE_RATIO) if context_window else 0
        _raw_wt = getattr(self._config, "max_session_wall_time_seconds", 0)
        wall_limit = _raw_wt if isinstance(_raw_wt, int | float) else 0
        wall_start = time.monotonic()

        while state.iteration < self._max_iterations:
            state.iteration += 1

            # Wall-time guardrail
            if wall_limit > 0:
                elapsed = time.monotonic() - wall_start
                if elapsed >= wall_limit:
                    logger.warning(
                        "Session wall-time limit reached: {:.0f}s >= {}s", elapsed, wall_limit
                    )
                    final_content = f"Session duration limit reached ({wall_limit}s). Please start a new conversation."
                    break

            # Context compression
            if ctx_budget and estimate_messages_tokens(state.messages) > int(ctx_budget * 0.85):
                _raw_sm = getattr(self._config, "summary_model", None)
                summary_model = (
                    _raw_sm if isinstance(_raw_sm, str) else None
                ) or self._llm_caller.model
                preserve_n = _dynamic_preserve_recent(state.messages, state.last_tool_call_msg_idx)
                if self._provider is not None:
                    state.messages = await summarize_and_compress(
                        state.messages,
                        ctx_budget,
                        provider=self._provider,
                        model=summary_model,
                        tool_token_threshold=_safe_int(
                            self._config, "tool_result_context_tokens", 2000
                        ),
                        preserve_recent=preserve_n,
                    )

            # Tool definition filtering (disabled_tools exclusion)
            if frozenset(state.disabled_tools) != state.tools_def_snapshot:
                state.tools_def_cache = [
                    t
                    for t in self._tool_executor.get_definitions()
                    if t["function"]["name"] not in state.disabled_tools
                ]
                state.tools_def_snapshot = frozenset(state.disabled_tools)
            active_tools = state.tools_def_cache if not state.nudged_for_final else None

            # LLM call (streaming when progress callback exists)
            if on_progress and state.iteration > 1:
                await on_progress(StatusEvent(status_code="thinking"))
            raw_response = await self._llm_caller.call(state.messages, active_tools, on_progress)

            # Normalise: test mocks may return (content, tool_calls) tuples
            if isinstance(raw_response, tuple):
                from nanobot.providers.base import LLMResponse as _LLMResponse

                _c, _tc = raw_response
                response: LLMResponse = _LLMResponse(content=_c, tool_calls=_tc or [])
            else:
                response = raw_response
            self._turn_llm_calls += 1
            self._turn_tokens_prompt += response.usage.get("prompt_tokens", 0)
            self._turn_tokens_completion += response.usage.get("completion_tokens", 0)

            # LLM error handling
            action, err_content = await self._handle_llm_error(state, response, on_progress)
            if action == "continue":
                continue
            if action == "break":
                final_content = err_content
                break
            state.consecutive_errors = 0

            # --- Tool calls present: execute batch ---
            if response.has_tool_calls:
                valid = [
                    tc for tc in response.tool_calls if tc.name and tc.name.strip() and tc.arguments
                ]
                skipped = len(response.tool_calls) - len(valid)
                if skipped:
                    logger.warning("Filtered {} malformed tool call(s)", skipped)
                if not valid:
                    if (
                        not response.content
                        and state.turn_tool_calls > 0
                        and not state.nudged_for_final
                    ):
                        state.nudged_for_final = True
                        state.messages.append({"role": "system", "content": _NUDGE_MALFORMED})
                        continue
                    final_content = strip_think(response.content)
                    state.messages = self._context.add_assistant_message(
                        state.messages, final_content, reasoning_content=response.reasoning_content
                    )
                    break

                from nanobot.providers.base import LLMResponse

                response = LLMResponse(
                    content=response.content,
                    tool_calls=valid,
                    finish_reason=response.finish_reason,
                    usage=response.usage,
                    reasoning_content=response.reasoning_content,
                )
                if on_progress:
                    await on_progress(StatusEvent(status_code="calling_tool"))
                    for tc in response.tool_calls:
                        await on_progress(
                            ToolCallEvent(tool_call_id=tc.id, tool_name=tc.name, args=tc.arguments)
                        )

                await self._execute_tool_batch(state, response, tools_used, on_progress)
            else:
                # No tool calls: text answer
                if (
                    not response.content
                    and state.turn_tool_calls > 0
                    and not state.nudged_for_final
                ):
                    state.nudged_for_final = True
                    state.messages.append({"role": "system", "content": _NUDGE_FINAL})
                    logger.info(
                        "Tool results present but no final text; retrying once for final answer."
                    )
                    continue
                final_content = strip_think(response.content)
                state.messages = self._context.add_assistant_message(
                    state.messages, final_content, reasoning_content=response.reasoning_content
                )
                break

        # Max iterations fallback
        if final_content is None and state.iteration >= self._max_iterations:
            logger.warning("Max iterations ({}) reached", self._max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self._max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )
            state.messages = self._context.add_assistant_message(state.messages, final_content)

        # Configurable self-check (replaces AnswerVerifier.verify)
        if final_content is not None:
            final_content = await self._self_check(final_content, state)

        return TurnResult(
            content=final_content or "",
            tools_used=tools_used,
            messages=state.messages,
            tokens_prompt=self._turn_tokens_prompt,
            tokens_completion=self._turn_tokens_completion,
            llm_calls=self._turn_llm_calls,
        )

    # ------------------------------------------------------------------
    # Tool execution (inlined from ActPhase)
    # ------------------------------------------------------------------

    async def _execute_tool_batch(
        self,
        state: TurnState,
        response: LLMResponse,
        tools_used: list[str],
        on_progress: ProgressCallback | None,
    ) -> None:
        """Execute a batch of tool calls, process results, run guardrails."""
        args_json: dict[str, str] = {
            tc.id: json.dumps(tc.arguments, ensure_ascii=False) for tc in response.tool_calls
        }
        tool_call_dicts = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": args_json[tc.id]},
            }
            for tc in response.tool_calls
        ]
        reasoning = response.reasoning_content or response.content
        new_msgs = self._context.add_assistant_message(
            state.messages, None, tool_call_dicts, reasoning_content=reasoning
        )
        state.last_tool_call_msg_idx = len(new_msgs) - 1
        state.messages[:] = new_msgs

        t0 = time.monotonic()
        results = await self._tool_executor.execute_batch(response.tool_calls)
        elapsed_ms = (time.monotonic() - t0) * 1000

        latest_attempts: list[ToolAttempt] = []
        to_remove: list[str] = []

        for tc, result in zip(response.tool_calls, results):
            state.turn_tool_calls += 1
            tools_used.append(tc.name)
            status = "OK" if result.success else "FAIL"
            bind_trace().info("tool_exec | {} | {} | {:.0f}ms batch", status, tc.name, elapsed_ms)
            if tc.name not in _ARGS_REDACT_TOOLS:
                bind_trace().debug("tool_exec args | {}({})", tc.name, args_json[tc.id][:200])
            if on_progress:
                await on_progress(
                    ToolResultEvent(
                        tool_call_id=tc.id, result=result.to_llm_string(), tool_name=tc.name
                    )
                )
            state.messages[:] = self._context.add_tool_result(
                state.messages, tc.id, tc.name, result.to_llm_string()
            )

            # Skill content injection
            sk = result.metadata.get("skill_content")
            if sk:
                sk_name = result.metadata.get("skill_name", "unknown")
                state.messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"# Skill: {sk_name}\n\nFollow these instructions to handle the user's request.\n\n{sk}"
                        ),
                    }
                )

            # Build ToolAttempt for working memory
            output_str = result.to_llm_string()
            attempt = ToolAttempt(
                tool_name=tc.name,
                arguments=tc.arguments,
                success=result.success,
                output_empty=result.success and _is_output_empty(output_str),
                output_snippet=output_str[:200],
                iteration=state.iteration,
            )
            latest_attempts.append(attempt)
            state.tool_results_log.append(attempt)

            # Failure / success tracking
            if not result.success:
                count, fc = state.tracker.record_failure(tc.name, tc.arguments, result)
                if count >= ToolCallTracker.REMOVE_THRESHOLD or fc.is_permanent:
                    to_remove.append(tc.name)
                    reason = (
                        f"permanently unavailable ({fc.value})"
                        if fc.is_permanent
                        else f"failed {count} times with identical arguments"
                    )
                    state.messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"TOOL REMOVED: `{tc.name}` is {reason} and has been disabled. Use a different approach."
                            ),
                        }
                    )
                elif count >= ToolCallTracker.WARN_THRESHOLD:
                    state.messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"STOP: `{tc.name}` has failed {count} times with the same arguments and error. "
                                "Do NOT call it again with the same arguments. Use a different approach or provide your best answer."
                            ),
                        }
                    )
            else:
                sc = state.tracker.record_success(tc.name, tc.arguments)
                if sc >= ToolCallTracker.REPEAT_SUCCESS_THRESHOLD:
                    to_remove.append(tc.name)
                    state.messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"TOOL REMOVED: `{tc.name}` has been called {sc} times with identical arguments "
                                "and is not making progress. It has been disabled. Use a different approach or provide your best answer."
                            ),
                        }
                    )

        state.disabled_tools.update(to_remove)

        # Global failure budget: force final answer
        if state.tracker.budget_exhausted:
            state.messages.append(
                {
                    "role": "system",
                    "content": (
                        f"You have {state.tracker.total_failures} failed tool calls this turn. "
                        "Stop calling tools and produce your final answer NOW with whatever information you have."
                    ),
                }
            )
            state.nudged_for_final = True

        update_current_span(
            metadata={
                "batch_tools": [tc.name for tc in response.tool_calls],
                "batch_any_failed": any(not a.success for a in latest_attempts),
                "batch_duration_ms": round(elapsed_ms),
            }
        )

        # Guardrail checkpoint
        intervention = self._guardrails.check(
            state.tool_results_log, latest_attempts, iteration=state.iteration
        )
        if intervention is not None:
            logger.info(
                "Guardrail '{}' fired (severity={}): {}",
                intervention.source,
                intervention.severity,
                intervention.message[:120],
            )
            state.messages.append({"role": "system", "content": intervention.message})
            state.guardrail_activations.append(
                {
                    "source": intervention.source,
                    "severity": intervention.severity,
                    "iteration": state.iteration,
                    "message": intervention.message,
                }
            )

    # ------------------------------------------------------------------
    # Self-check (replaces AnswerVerifier.verify)
    # ------------------------------------------------------------------

    async def _self_check(self, content: str, state: TurnState) -> str:
        """Run structured self-check if configured; otherwise no-op."""
        mode = getattr(self._config, "verification_mode", "off")
        if mode != "structured" or self._provider is None:
            return content
        from nanobot.context.prompt_loader import prompts

        prompt = prompts.get("self_check")
        if not prompt:
            return content
        check_msgs = state.messages + [
            {
                "role": "system",
                "content": (
                    f"{prompt}\n\nReview your response above. If any check fails, "
                    "produce a corrected version. Otherwise repeat your response unchanged."
                ),
            }
        ]
        try:
            resp = await self._provider.chat(
                messages=check_msgs,
                tools=None,
                model=self._llm_caller.model,
                temperature=0.0,
                max_tokens=self._llm_caller.max_tokens,
            )
            revised = strip_think(resp.content)
            if revised:
                self._turn_llm_calls += 1
                self._turn_tokens_prompt += resp.usage.get("prompt_tokens", 0)
                self._turn_tokens_completion += resp.usage.get("completion_tokens", 0)
                return revised
        except Exception:  # crash-barrier: self-check LLM call
            logger.debug("Self-check call failed, returning original answer")
        return content

    # ------------------------------------------------------------------
    # LLM error handling (preserved exactly from TurnOrchestrator)
    # ------------------------------------------------------------------

    async def _handle_llm_error(
        self,
        state: TurnState,
        response: LLMResponse,
        on_progress: ProgressCallback | None,
    ) -> tuple[Literal["continue", "break", "proceed"], str | None]:
        """Handle LLM-level error finish reasons."""
        if response.finish_reason == "error":
            state.consecutive_errors += 1
            logger.warning(
                "LLM returned error (attempt {}): {}", state.consecutive_errors, response.content
            )
            if state.consecutive_errors >= 3:
                fc = "I'm having trouble reaching the language model right now. Please try again in a moment."
                state.messages[:] = self._context.add_assistant_message(state.messages, fc)
                return "break", fc
            if on_progress:
                await on_progress(StatusEvent(status_code="retrying"))
            await asyncio.sleep(min(2**state.consecutive_errors, 10))
            return "continue", None

        if response.finish_reason == "content_filter":
            state.consecutive_errors += 1
            logger.warning("Content filter triggered (attempt {})", state.consecutive_errors)
            if state.consecutive_errors >= 2:
                fc = "The AI provider's content filter blocked my response. Try rephrasing your question."
                state.messages[:] = self._context.add_assistant_message(state.messages, fc)
                return "break", fc
            await asyncio.sleep(1)
            return "continue", None

        if response.finish_reason == "length" and not response.content:
            state.consecutive_errors += 1
            logger.warning(
                "Response truncated to zero content (attempt {})", state.consecutive_errors
            )
            if state.consecutive_errors >= 2:
                fc = (
                    "My response was too long and got cut off. Try asking a more specific question."
                )
                state.messages[:] = self._context.add_assistant_message(state.messages, fc)
                return "break", fc
            await asyncio.sleep(1)
            return "continue", None

        return "proceed", None
