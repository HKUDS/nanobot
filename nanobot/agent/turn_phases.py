"""ACT and REFLECT phase handlers for the PAOR loop.

Extracted from ``turn_orchestrator.py`` to keep both files under 500 LOC.
``ActPhase`` owns tool execution and result processing; ``ReflectPhase``
owns post-batch progress evaluation and delegation nudges.

Module boundary: this module must **never** import from ``nanobot.channels.*``,
``nanobot.bus.*``, or ``nanobot.session.*``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nanobot.agent.callbacks import ProgressCallback, ToolResultEvent
from nanobot.agent.failure import FailureClass, ToolCallTracker, _build_failure_prompt
from nanobot.agent.turn_types import TurnState
from nanobot.context.context import ContextBuilder
from nanobot.coordination.task_types import has_parallel_structure
from nanobot.observability.langfuse import update_current_span
from nanobot.observability.tracing import bind_trace
from nanobot.tools.executor import ToolExecutor

if TYPE_CHECKING:
    from nanobot.context.prompt_loader import PromptLoader
    from nanobot.coordination.delegation import DelegationDispatcher
    from nanobot.coordination.delegation_advisor import DelegationAdvisor
    from nanobot.providers.base import LLMResponse

# ---------------------------------------------------------------------------
# Module constants (moved from turn_orchestrator.py)
# ---------------------------------------------------------------------------

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
# Module-level private helpers (moved from turn_orchestrator.py)
# ---------------------------------------------------------------------------


def _safe_int(obj: Any, attr: str, default: int) -> int:
    """Safely extract an integer attribute, returning *default* when the value is not numeric."""
    val = getattr(obj, attr, default)
    return int(val) if isinstance(val, int | float) else default


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
# ToolBatchResult
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToolBatchResult:
    """Return value of ``ActPhase.execute_tools`` -- scalar state that changes per batch."""

    any_failed: bool
    failed_this_batch: list[tuple[str, FailureClass]]
    nudged_for_final: bool
    last_tool_call_msg_idx: int
    tool_calls_this_batch: int


# ---------------------------------------------------------------------------
# ActPhase
# ---------------------------------------------------------------------------


class ActPhase:
    """Execute tool calls and process their results (ACT + OBSERVE phases)."""

    def __init__(self, *, tool_executor: ToolExecutor, context: ContextBuilder) -> None:
        self._tool_executor = tool_executor
        self._context = context

    async def execute_tools(
        self,
        state: TurnState,
        response: LLMResponse,
        tools_used: list[str],
        on_progress: ProgressCallback | None,
    ) -> ToolBatchResult:
        """Execute tool calls and process their results.

        Mutates ``state.messages``, *tools_used*, and ``state.disabled_tools``
        in-place.  Returns a ``ToolBatchResult`` with the scalar state changes.
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
            # Skill content injection: deliver as a system message so it
            # carries the same authority as the identity prompt.
            _skill_content = result.metadata.get("skill_content")
            if _skill_content:
                _skill_name = result.metadata.get("skill_name", "unknown")
                state.messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"# Skill: {_skill_name}\n\n"
                            "Follow these instructions to handle the user's request.\n\n"
                            f"{_skill_content}"
                        ),
                    }
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
                success_count = state.tracker.record_success(tool_call.name, tool_call.arguments)
                if success_count >= ToolCallTracker.REPEAT_SUCCESS_THRESHOLD:
                    tools_to_remove.append(tool_call.name)
                    state.messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"TOOL REMOVED: `{tool_call.name}` has been called "
                                f"{success_count} times with identical arguments and "
                                "is not making progress. It has been disabled. "
                                "Use a different approach or provide your best answer."
                            ),
                        }
                    )

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

        update_current_span(
            metadata={
                "batch_tools": [tc.name for tc in response.tool_calls],
                "batch_any_failed": any_failed,
                "batch_duration_ms": round(tools_elapsed_ms),
            }
        )

        return ToolBatchResult(
            any_failed=any_failed,
            failed_this_batch=failed_this_batch,
            nudged_for_final=nudged_for_final,
            last_tool_call_msg_idx=last_tool_call_msg_idx,
            tool_calls_this_batch=tool_calls_this_batch,
        )


# ---------------------------------------------------------------------------
# ReflectPhase
# ---------------------------------------------------------------------------


class ReflectPhase:
    """Evaluate progress and inject REFLECT-phase guidance."""

    def __init__(
        self,
        *,
        dispatcher: DelegationDispatcher,
        delegation_advisor: DelegationAdvisor,
        prompts: PromptLoader,
        role_name: str,
    ) -> None:
        self._dispatcher = dispatcher
        self._delegation_advisor = delegation_advisor
        self._prompts = prompts
        self._role_name = role_name

    def evaluate(
        self,
        state: TurnState,
        response: LLMResponse,
        any_failed: bool,
        failed_this_batch: list[tuple[str, FailureClass]],
        *,
        role_name: str | None = None,
    ) -> None:
        """Append REFLECT-phase system messages based on the current turn state.

        Mutates ``state`` in-place: updates ``last_delegation_advice`` and may
        filter ``tools_def_cache`` when delegate tools are removed.

        Parameters
        ----------
        role_name:
            Optional per-call override for the active role.  When provided,
            takes precedence over the construction-time ``_role_name``.
        """
        from nanobot.coordination.delegation_advisor import DelegationAction

        effective_role = role_name if role_name is not None else self._role_name

        had_delegations = any(tc.name in _DELEGATION_TOOL_NAMES for tc in response.tool_calls)

        # --- Delegation advisor (replaces 3 independent triggers) ---
        delegation_advice = self._delegation_advisor.advise_reflect_phase(
            role_name=effective_role,
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
                {
                    "role": "system",
                    "content": self._prompts.get("nudge_delegation_exhausted"),
                }
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
                    {
                        "role": "system",
                        "content": self._prompts.get("nudge_use_parallel"),
                    }
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
