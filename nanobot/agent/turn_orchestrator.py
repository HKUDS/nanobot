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
import time
from typing import TYPE_CHECKING, Literal

from loguru import logger

from nanobot.agent.callbacks import (
    ProgressCallback,
    StatusEvent,
    ToolCallEvent,
)
from nanobot.agent.streaming import StreamingLLMCaller, strip_think
from nanobot.agent.turn_phases import (
    _CONTEXT_RESERVE_RATIO,
    ActPhase,
    _dynamic_preserve_recent,
    _needs_planning,
    _safe_int,
)
from nanobot.agent.turn_types import TurnResult as TurnResult  # re-export
from nanobot.agent.turn_types import TurnState as TurnState  # re-export
from nanobot.agent.verifier import AnswerVerifier
from nanobot.context.compression import estimate_messages_tokens, summarize_and_compress
from nanobot.context.context import ContextBuilder
from nanobot.context.prompt_loader import PromptLoader
from nanobot.tools.executor import ToolExecutor

if TYPE_CHECKING:
    from nanobot.config.agent import AgentConfig
    from nanobot.providers.base import LLMProvider, LLMResponse


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
        config: AgentConfig,
        prompts: PromptLoader,
        context: ContextBuilder,
        provider: LLMProvider | None = None,
        model: str = "",
        role_name: str = "",
    ) -> None:
        self._llm_caller = llm_caller
        self._tool_executor = tool_executor
        self._verifier = verifier
        self._config = config
        self._prompts = prompts
        self._context = context
        self._provider = provider
        self._model = model
        self._max_iterations = config.max_iterations
        self._role_name = role_name

        # Phase handlers (extracted to turn_phases.py)
        self._act = ActPhase(tool_executor=tool_executor, context=context)

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
        final_content: str | None = None
        tools_used: list[str] = []

        # Reset per-turn token accumulators
        self._turn_tokens_prompt = 0
        self._turn_tokens_completion = 0
        self._turn_llm_calls = 0

        # Resolve per-turn active settings (role-switched overrides).
        effective_model = state.active_model if state.active_model is not None else self._model
        max_iterations = (
            state.active_max_iterations
            if state.active_max_iterations is not None
            else self._max_iterations
        )

        # Reserve ~20% of context window for the model's response
        _raw_cw = getattr(self._config, "context_window_tokens", 0)
        context_window = _raw_cw if isinstance(_raw_cw, int | float) else 0
        context_budget = int(context_window * _CONTEXT_RESERVE_RATIO) if context_window else 0

        # --- PLAN phase: inject planning prompt for complex tasks ----------
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

        _raw_wt = getattr(self._config, "max_session_wall_time_seconds", 0)
        _wall_time_limit = _raw_wt if isinstance(_raw_wt, int | float) else 0
        _wall_time_start = time.monotonic()

        while state.iteration < max_iterations:
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
                summary_model = (_raw_sm if isinstance(_raw_sm, str) else None) or effective_model
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
                model=state.active_model,
                temperature=state.active_temperature,
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
                batch = await self._act.execute_tools(
                    state,
                    response,
                    tools_used,
                    on_progress,
                )
                state.turn_tool_calls += batch.tool_calls_this_batch
                state.nudged_for_final = batch.nudged_for_final
                state.last_tool_call_msg_idx = batch.last_tool_call_msg_idx

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

        if final_content is None and state.iteration >= max_iterations:
            logger.warning("Max iterations ({}) reached", max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )
            state.messages = self._context.add_assistant_message(state.messages, final_content)

        # --- Verification pass ---------------------------------------------
        if final_content is not None:
            final_content, state.messages = await self._verifier.verify(
                state.user_text,
                final_content,
                state.messages,
                model=state.active_model,
                temperature=state.active_temperature,
            )

        return TurnResult(
            content=final_content or "",
            tools_used=tools_used,
            messages=state.messages,
            tokens_prompt=self._turn_tokens_prompt,
            tokens_completion=self._turn_tokens_completion,
            llm_calls=self._turn_llm_calls,
        )

    # ------------------------------------------------------------------
    # Internal helpers
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
