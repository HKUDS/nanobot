"""Turn orchestrator: the Plan-Act-Observe-Reflect state machine.

``TurnOrchestrator`` owns the PAOR loop and the ``TurnState`` that tracks
its mutable state across iterations.  Collaborators are injected at
construction time.

Extracted from ``AgentLoop._run_agent_loop`` (Task 6 of the loop
decomposition).  See ``docs/superpowers/specs/2026-03-22-loop-decomposition-design.md``,
Section 3.

Module boundary: this module must **never** import from ``nanobot.channels.*``,
``nanobot.bus.*``, or ``nanobot.session.*``.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from nanobot.agent.callbacks import (
    ProgressCallback,
    StatusEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.agent.compression import estimate_messages_tokens, summarize_and_compress
from nanobot.agent.context import ContextBuilder
from nanobot.agent.failure import FailureClass, ToolCallTracker, _build_failure_prompt
from nanobot.agent.prompt_loader import PromptLoader
from nanobot.agent.streaming import StreamingLLMCaller, strip_think
from nanobot.agent.tracing import bind_trace
from nanobot.agent.turn_types import TurnResult as TurnResult  # re-export
from nanobot.agent.turn_types import TurnState as TurnState  # re-export
from nanobot.agent.verifier import AnswerVerifier
from nanobot.coordination.delegation import DelegationDispatcher
from nanobot.coordination.task_types import has_parallel_structure
from nanobot.tools.executor import ToolExecutor

if TYPE_CHECKING:
    from nanobot.config.schema import AgentConfig
    from nanobot.coordination.delegation_advisor import DelegationAdvisor
    from nanobot.providers.base import LLMProvider, LLMResponse

# Tools whose arguments may contain sensitive data (file contents, credentials,
# command strings). Their call arguments are omitted from structured log output
# to prevent leaking sensitive information into log files or tracing backends.
_ARGS_REDACT_TOOLS: frozenset[str] = frozenset(
    {"write_file", "edit_file", "exec", "web_fetch", "web_search"}
)

# Delegation tool names -- hoisted here to avoid rebuilding the set each iteration.
_DELEGATION_TOOL_NAMES: frozenset[str] = frozenset({"delegate", "delegate_parallel"})

# Named constants for magic numbers used across the agent loop (CQ-L6).
_GREETING_MAX_LEN: int = 20  # Messages shorter than this are treated as greetings / simple Qs
_CONTEXT_RESERVE_RATIO: float = (
    0.80  # Fraction of context window reserved for prompt; ~20% for reply
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


# ---------------------------------------------------------------------------
# Module-level private helpers (moved from loop.py)
# ---------------------------------------------------------------------------


def _safe_int(obj: Any, attr: str, default: int) -> int:
    """Safely extract an integer attribute, returning *default* when the value is not numeric."""
    val = getattr(obj, attr, default)
    return int(val) if isinstance(val, (int, float)) else default


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


def _dynamic_preserve_recent(
    messages: list[dict[str, Any]],
    last_tool_call_idx: int = -1,
    *,
    floor: int = 6,
    cap: int = 30,
) -> int:
    """Calculate how many tail messages to preserve during compression.

    Ensures the last complete tool-call cycle (assistant with tool_calls ->
    all corresponding tool results -> next message) is never split.
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


# ---------------------------------------------------------------------------
# TurnState and TurnResult
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ToolBatchResult:
    """Return value of ``_process_tool_results`` -- scalar state that changes per batch."""

    any_failed: bool
    failed_this_batch: list[tuple[str, FailureClass]]
    nudged_for_final: bool
    last_tool_call_msg_idx: int
    tool_calls_this_batch: int


# ---------------------------------------------------------------------------
# TurnOrchestrator
# ---------------------------------------------------------------------------


class TurnOrchestrator:
    """Plan-Act-Observe-Reflect state machine.

    Owns the PAOR loop and the ``TurnState``.  Collaborators are injected at
    construction time; the orchestrator never imports from ``channels/``,
    ``bus/``, or ``session/``.
    """

    def __init__(
        self,
        *,
        llm_caller: StreamingLLMCaller,
        tool_executor: ToolExecutor,
        verifier: AnswerVerifier,
        dispatcher: DelegationDispatcher,
        delegation_advisor: DelegationAdvisor,
        config: AgentConfig,
        prompts: PromptLoader,
        context: ContextBuilder,
        # Note: spec Section 3 defines 8 keyword-only params. Three additional params
        # (provider, model, role_name) are needed for context compression and delegation
        # routing. Eliminating them would require changes to ContextBuilder or
        # DelegationAdvisor — explicitly out-of-scope per design spec Section 6.
        provider: LLMProvider | None = None,
        model: str = "",
        role_name: str = "",
    ) -> None:
        self._llm_caller = llm_caller
        self._tool_executor = tool_executor
        self._verifier = verifier
        self._dispatcher = dispatcher
        self._delegation_advisor = delegation_advisor
        self._config = config
        self._prompts = prompts
        self._context = context
        self._provider = provider
        self._model = model
        self._max_iterations = config.max_iterations
        self._role_name = role_name

        # Per-turn token accumulators (reset at start of each run)
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        # _last_classification_result removed: now passed via TurnState.classification_result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        state: TurnState,
        on_progress: ProgressCallback | None,
    ) -> TurnResult:
        """Run the Plan-Act-Observe-Reflect agent loop.

        Returns a ``TurnResult`` with the final content, tool names used,
        and the conversation message list after the turn.
        """
        self._dispatcher.on_progress = on_progress
        self._dispatcher.active_messages = state.messages
        self._dispatcher.delegation_count = 0
        final_content: str | None = None
        tools_used: list[str] = []

        # Reset per-turn token accumulators
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        # Reserve ~20% of context window for the model's response
        _raw_cw = getattr(self._config, "context_window_tokens", 0)
        context_window = _raw_cw if isinstance(_raw_cw, (int, float)) else 0
        context_budget = int(context_window * _CONTEXT_RESERVE_RATIO) if context_window else 0

        # --- PLAN phase: inject planning prompt for complex tasks ----------
        from nanobot.coordination.delegation_advisor import DelegationAction

        _raw_pe = getattr(self._config, "planning_enabled", False)
        planning_enabled = _raw_pe if isinstance(_raw_pe, bool) else False
        if planning_enabled:
            if _needs_planning(state.user_text):
                state.messages.append(
                    {
                        "role": "system",
                        "content": self._prompts.get("plan"),
                    }
                )
                state.has_plan = True
                logger.debug("Planning prompt injected for: {}...", state.user_text[:60])
                # Delegation advisor plan-phase
                cr = state.classification_result
                plan_advice = self._delegation_advisor.advise_plan_phase(
                    role_name=self._role_name,
                    needs_orchestration=cr.needs_orchestration if cr else False,
                    relevant_roles=cr.relevant_roles if cr else [],
                    user_text=state.user_text,
                    delegate_tools_available=bool(self._tool_executor.get("delegate_parallel")),
                )
                if plan_advice.action != DelegationAction.NONE:
                    state.messages.append(
                        {
                            "role": "system",
                            "content": self._prompts.get("nudge_parallel_structure"),
                        }
                    )
                    logger.debug("Delegation advisor plan-phase: {}", plan_advice.reason)

        _raw_wt = getattr(self._config, "max_session_wall_time_seconds", 0)
        _wall_time_limit = _raw_wt if isinstance(_raw_wt, (int, float)) else 0
        _wall_time_start = time.monotonic()

        while state.iteration < self._max_iterations:
            state.iteration += 1

            # Wall-time guardrail (LAN-193)
            if _wall_time_limit > 0:
                elapsed = time.monotonic() - _wall_time_start
                if elapsed >= _wall_time_limit:
                    logger.warning(
                        "Session wall-time limit reached: {:.0f}s >= {}s",
                        elapsed,
                        _wall_time_limit,
                    )
                    final_content = (
                        f"Session duration limit reached ({_wall_time_limit}s). "
                        "Please start a new conversation."
                    )
                    break

            # --- Context compression: keep messages within budget ----------
            if context_budget and estimate_messages_tokens(state.messages) > int(
                context_budget * 0.85
            ):
                _raw_sm = getattr(self._config, "summary_model", None)
                summary_model = (_raw_sm if isinstance(_raw_sm, str) else None) or self._model
                preserve_n = _dynamic_preserve_recent(state.messages, state.last_tool_call_msg_idx)
                if self._provider is not None:
                    state.messages = await summarize_and_compress(
                        state.messages,
                        context_budget,
                        provider=self._provider,
                        model=summary_model,
                        tool_token_threshold=_safe_int(
                            self._config, "tool_result_context_tokens", 2000
                        ),
                        preserve_recent=preserve_n,
                    )

            # Exclude tools disabled this turn (failure threshold or permanent failure).
            if frozenset(state.disabled_tools) != state.tools_def_snapshot:
                state.tools_def_cache = [
                    t
                    for t in self._tool_executor.get_definitions()
                    if t["function"]["name"] not in state.disabled_tools
                ]
                state.tools_def_snapshot = frozenset(state.disabled_tools)
            tools_def = state.tools_def_cache
            active_tools = tools_def if not state.nudged_for_final else None

            # --- LLM call (streaming when a progress callback exists) ------
            if on_progress and state.iteration > 1:
                await on_progress(StatusEvent(status_code="thinking"))
            raw_response = await self._llm_caller.call(
                state.messages,
                active_tools,
                on_progress,
            )
            # Normalise: in tests, mocks may return (content, tool_calls) tuples
            # instead of LLMResponse objects.
            if isinstance(raw_response, tuple):
                from nanobot.providers.base import LLMResponse as _LLMResponse

                _content, _tcs = raw_response
                response: LLMResponse = _LLMResponse(content=_content, tool_calls=_tcs or [])
            else:
                response = raw_response
            # Accumulate token usage from this LLM call
            self._turn_llm_calls += 1
            self._turn_tokens_prompt += response.usage.get("prompt_tokens", 0)
            self._turn_tokens_completion += response.usage.get("completion_tokens", 0)

            # --- Check for LLM-level errors --------------------------------
            _err_action, _err_content = await self._handle_llm_error(state, response, on_progress)
            if _err_action == "continue":
                continue
            if _err_action == "break":
                final_content = _err_content
                break

            state.consecutive_errors = 0

            # --- ACT: execute tool calls -----------------------------------
            if response.has_tool_calls:
                # Plan enforcement: if planning was requested but model jumped
                # straight to tools without producing a plan, nudge it once.
                is_delegation = all(tc.name in _DELEGATION_TOOL_NAMES for tc in response.tool_calls)
                if (
                    state.has_plan
                    and not state.plan_enforced
                    and state.turn_tool_calls == 0
                    and not response.content
                    and not is_delegation
                ):
                    state.plan_enforced = True
                    state.messages.append(
                        {
                            "role": "system",
                            "content": self._prompts.get("nudge_plan_enforcement"),
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
                    # All calls were malformed -- treat as empty response
                    if (
                        not response.content
                        and state.turn_tool_calls > 0
                        and not state.nudged_for_final
                    ):
                        state.nudged_for_final = True
                        state.messages.append(
                            {
                                "role": "system",
                                "content": self._prompts.get("nudge_malformed_fallback"),
                            }
                        )
                        continue
                    final_content = strip_think(response.content)
                    state.messages = self._context.add_assistant_message(
                        state.messages,
                        final_content,
                        reasoning_content=response.reasoning_content,
                    )
                    break

                # Replace with filtered list
                from nanobot.providers.base import LLMResponse

                response = LLMResponse(
                    content=response.content,
                    tool_calls=valid_calls,
                    finish_reason=response.finish_reason,
                    usage=response.usage,
                    reasoning_content=response.reasoning_content,
                )

                if on_progress:
                    await on_progress(StatusEvent(status_code="calling_tool"))
                    for tc in response.tool_calls:
                        await on_progress(
                            ToolCallEvent(
                                tool_call_id=tc.id,
                                tool_name=tc.name,
                                args=tc.arguments,
                            )
                        )

                # --- ACT + OBSERVE: execute tools and process results ------
                batch = await self._process_tool_results(
                    state,
                    response,
                    tools_used,
                    on_progress,
                )
                state.turn_tool_calls += batch.tool_calls_this_batch
                state.nudged_for_final = batch.nudged_for_final
                state.last_tool_call_msg_idx = batch.last_tool_call_msg_idx

                # --- REFLECT: evaluate progress and inject guidance ---------
                self._evaluate_progress(
                    state,
                    response,
                    batch.any_failed,
                    batch.failed_this_batch,
                )

            else:
                # --- No tool calls: the model is producing a text answer ---
                if (
                    not response.content
                    and state.turn_tool_calls > 0
                    and not state.nudged_for_final
                ):
                    state.nudged_for_final = True
                    state.messages.append(
                        {
                            "role": "system",
                            "content": self._prompts.get("nudge_final_answer"),
                        }
                    )
                    logger.info(
                        "Tool results present but no final text; retrying once for final answer."
                    )
                    continue
                final_content = strip_think(response.content)
                state.messages = self._context.add_assistant_message(
                    state.messages,
                    final_content,
                    reasoning_content=response.reasoning_content,
                )
                break

        if final_content is None and state.iteration >= self._max_iterations:
            logger.warning("Max iterations ({}) reached", self._max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self._max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )
            state.messages = self._context.add_assistant_message(state.messages, final_content)

        # --- Verification pass ---------------------------------------------
        if final_content is not None:
            final_content, state.messages = await self._verifier.verify(
                state.user_text,
                final_content,
                state.messages,
            )

        # Clear per-turn progress callback to prevent cross-turn leakage
        self._dispatcher.on_progress = None

        return TurnResult(
            content=final_content or "",
            tools_used=tools_used,
            messages=state.messages,
            tokens_prompt=self._turn_tokens_prompt,
            tokens_completion=self._turn_tokens_completion,
            llm_calls=self._turn_llm_calls,
        )

    # ------------------------------------------------------------------
    # Internal helpers (moved from AgentLoop)
    # ------------------------------------------------------------------

    async def _handle_llm_error(
        self,
        state: TurnState,
        response: LLMResponse,
        on_progress: ProgressCallback | None,
    ) -> tuple[Literal["continue", "break", "proceed"], str | None]:
        """Handle LLM-level error finish reasons.

        Returns ``(action, final_content)`` where *action*
        is ``"continue"`` (retry this iteration), ``"break"`` (end the loop),
        or ``"proceed"`` (no error -- continue normal processing).
        Mutates ``state.consecutive_errors`` and ``state.messages`` in-place.
        """
        if response.finish_reason == "error":
            state.consecutive_errors += 1
            logger.warning(
                "LLM returned error (attempt {}): {}",
                state.consecutive_errors,
                response.content,
            )
            if state.consecutive_errors >= 3:
                final_content = (
                    "I'm having trouble reaching the language model right now. "
                    "Please try again in a moment."
                )
                state.messages[:] = self._context.add_assistant_message(
                    state.messages, final_content
                )
                return "break", final_content
            if on_progress:
                await on_progress(StatusEvent(status_code="retrying"))
            await asyncio.sleep(min(2**state.consecutive_errors, 10))
            return "continue", None

        if response.finish_reason == "content_filter":
            state.consecutive_errors += 1
            logger.warning("Content filter triggered (attempt {})", state.consecutive_errors)
            if state.consecutive_errors >= 2:
                final_content = (
                    "The AI provider's content filter blocked my response. "
                    "Try rephrasing your question."
                )
                state.messages[:] = self._context.add_assistant_message(
                    state.messages, final_content
                )
                return "break", final_content
            await asyncio.sleep(1)
            return "continue", None

        if response.finish_reason == "length" and not response.content:
            state.consecutive_errors += 1
            logger.warning(
                "Response truncated to zero content (attempt {})", state.consecutive_errors
            )
            if state.consecutive_errors >= 2:
                final_content = (
                    "My response was too long and got cut off. Try asking a more specific question."
                )
                state.messages[:] = self._context.add_assistant_message(
                    state.messages, final_content
                )
                return "break", final_content
            await asyncio.sleep(1)
            return "continue", None

        return "proceed", None

    async def _process_tool_results(
        self,
        state: TurnState,
        response: LLMResponse,
        tools_used: list[str],
        on_progress: ProgressCallback | None,
    ) -> _ToolBatchResult:
        """Execute tool calls and process their results.

        Mutates ``state.messages``, *tools_used*, and ``state.disabled_tools``
        in-place.  Returns a ``_ToolBatchResult`` with the scalar state changes.
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
        new_messages = self._context.add_assistant_message(
            state.messages,
            None,
            tool_call_dicts,
            reasoning_content=reasoning,
        )
        last_tool_call_msg_idx = len(new_messages) - 1
        state.messages[:] = new_messages

        # Execute tools (parallel for readonly, sequential for writes)
        t0_tools = time.monotonic()
        tool_results = await self._tool_executor.execute_batch(response.tool_calls)
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
                    ToolResultEvent(
                        tool_call_id=tool_call.id,
                        result=result.to_llm_string(),
                        tool_name=tool_call.name,
                    )
                )
            state.messages[:] = self._context.add_tool_result(
                state.messages, tool_call.id, tool_call.name, result.to_llm_string()
            )
            if not result.success:
                any_failed = True
                count, fc = state.tracker.record_failure(
                    tool_call.name, tool_call.arguments, result
                )
                failed_this_batch.append((tool_call.name, fc))
                remove_now = count >= ToolCallTracker.REMOVE_THRESHOLD or fc.is_permanent
                if remove_now:
                    tools_to_remove.append(tool_call.name)
                    reason = (
                        f"permanently unavailable ({fc.value})"
                        if fc.is_permanent
                        else f"failed {count} times with identical arguments"
                    )
                    state.messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"TOOL REMOVED: `{tool_call.name}` is {reason} "
                                "and has been disabled. Use a different approach."
                            ),
                        }
                    )
                elif count >= ToolCallTracker.WARN_THRESHOLD:
                    state.messages.append(
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
                state.tracker.record_success(tool_call.name, tool_call.arguments)

        state.disabled_tools.update(tools_to_remove)

        # Global failure budget: force final answer
        nudged_for_final = state.nudged_for_final
        if state.tracker.budget_exhausted:
            state.messages.append(
                {
                    "role": "system",
                    "content": (
                        f"You have {state.tracker.total_failures} failed tool calls "
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
        state: TurnState,
        response: LLMResponse,
        any_failed: bool,
        failed_this_batch: list[tuple[str, FailureClass]],
    ) -> None:
        """Append REFLECT-phase system messages based on the current turn state.

        Mutates ``state`` in-place: updates ``last_delegation_advice`` and may
        filter ``tools_def_cache`` when delegate tools are removed.
        """
        from nanobot.coordination.delegation_advisor import DelegationAction

        had_delegations = any(tc.name in _DELEGATION_TOOL_NAMES for tc in response.tool_calls)

        # --- Delegation advisor (replaces 3 independent triggers) ---
        delegation_advice = self._delegation_advisor.advise_reflect_phase(
            role_name=self._role_name,
            turn_tool_calls=state.turn_tool_calls,
            delegation_count=self._dispatcher.delegation_count,
            max_delegations=self._dispatcher.max_delegations,
            had_delegations_this_batch=had_delegations,
            used_sequential_delegate=had_delegations
            and not any(tc.name == "delegate_parallel" for tc in response.tool_calls),
            has_parallel_structure=has_parallel_structure(state.user_text),
            any_ungrounded=any(
                "grounded=False" in (m.get("content") or "")
                for m in state.messages[-len(response.tool_calls) :]
                if m.get("role") == "tool"
            ),
            any_failed=any_failed,
            iteration=state.iteration,
            previous_advice=state.last_delegation_advice,
        )
        state.last_delegation_advice = delegation_advice.action

        # --- Render delegation advice OR fall through to other nudges ---
        if delegation_advice.action == DelegationAction.HARD_GATE:
            state.messages.append(
                {"role": "system", "content": self._prompts.get("nudge_delegation_exhausted")}
            )
        elif delegation_advice.action == DelegationAction.SYNTHESIZE:
            nudge = self._prompts.get("nudge_post_delegation")
            if delegation_advice.warn_ungrounded:
                nudge += "\n\n" + self._prompts.get("nudge_ungrounded_warning")
            state.messages.append({"role": "system", "content": nudge})
        elif delegation_advice.action in (
            DelegationAction.SOFT_NUDGE,
            DelegationAction.HARD_NUDGE,
        ):
            if delegation_advice.suggested_mode == "delegate_parallel":
                state.messages.append(
                    {"role": "system", "content": self._prompts.get("nudge_use_parallel")}
                )
            else:
                state.messages.append({"role": "system", "content": delegation_advice.reason})
        elif any_failed:
            # PRESERVED: failure handling (advisor returns NONE when any_failed=True)
            _permanent = state.tracker.permanent_failures
            _available = [
                t["function"]["name"]
                for t in state.tools_def_cache
                if t["function"]["name"] not in _permanent
            ]
            state.messages.append(
                {
                    "role": "system",
                    "content": _build_failure_prompt(
                        failed_this_batch,
                        _permanent,
                        _available,
                    ),
                }
            )
        elif state.has_plan and len(response.tool_calls) >= 1:
            # PRESERVED: progress nudge (not delegation-related)
            state.messages.append(
                {
                    "role": "system",
                    "content": self._prompts.get("progress"),
                }
            )
        elif len(response.tool_calls) >= 3:
            # PRESERVED: reflect nudge (not delegation-related)
            state.messages.append(
                {
                    "role": "system",
                    "content": self._prompts.get("reflect"),
                }
            )

        # Remove delegate tools when advisor says budget is exhausted
        if delegation_advice.remove_delegate_tools:
            state.tools_def_cache = [
                t
                for t in state.tools_def_cache
                if t["function"]["name"] not in _DELEGATION_TOOL_NAMES
            ]
