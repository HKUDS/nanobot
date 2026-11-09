from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, ParamSpec, TypeVar, cast
from uuid import uuid4

from loguru import logger

from nanobot.agent.context import TranscriptInput
from nanobot.agent.context_governance import (
    ContextCompactionState,
    ContextGovernanceConfig,
    ContextGovernor,
    HistoryConsolidator,
    ModelRequestState,
    ProviderCompactionConsolidator,
    TranscriptBuilder,
)
from nanobot.agent.execution_policy import ExecutionControlError
from nanobot.agent.hook import AgentHook, AgentHookContext, AgentRunHookContext
from nanobot.agent.tools.context import tool_log_content_allowed
from nanobot.agent.tools.execution import ToolCallResult, execute_tool_calls
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.events import NO_EVENTS, EventSink, ModelRequestEvent
from nanobot.llm_usage.context import (
    LLMUsageSource,
    bind_llm_usage_source,
    reset_llm_usage_source,
    source_from_session_key,
)
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ProviderCallContext,
    ProviderConversationState,
)
from nanobot.providers.compaction import ProviderStateCommitError
from nanobot.providers.conversation_state import ProviderConversationStateController
from nanobot.session.history_visibility import HIDDEN_HISTORY_META, is_hidden_history_message
from nanobot.session.summary import SessionSummaryCheckpoint
from nanobot.utils.cancellation import shield_and_drain
from nanobot.utils.helpers import (
    build_assistant_message,
    estimate_message_tokens,
    estimate_prompt_tokens_chain,
    extract_reasoning,
    strip_reasoning_tags,
)
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.prompt_templates import render_template
from nanobot.utils.runtime import (
    EMPTY_FINAL_RESPONSE_MESSAGE,
    build_budget_exhausted_finalization_message,
    build_finalization_retry_message,
    build_length_recovery_message,
    is_blank_text,
)


def _raise_if_cancelling() -> None:
    """Do not resume model work when a dependency suppresses cancellation."""
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError


ContinuationCallback = Callable[[], Awaitable[str | None]]
CheckpointCallback = Callable[[dict[str, Any]], Awaitable[None]]
InjectionCallback = Callable[[], Awaitable[Iterable[Any] | None]]

_DEFAULT_ERROR_MESSAGE = "Sorry, I encountered an error calling the AI model."
_ARREARAGE_ERROR_MESSAGE = (
    "The AI provider rejected the request because the API key is out of quota or the "
    "account is in arrears. Please top up / check the billing status of your API key and try again."
)
_PERSISTED_MODEL_ERROR_PLACEHOLDER = "[Assistant reply unavailable due to model error.]"
_MAX_EMPTY_RETRIES = 2
_MAX_LENGTH_RECOVERIES = 3
_PromptArgs = ParamSpec("_PromptArgs")
_PromptResult = TypeVar("_PromptResult")


def _restore_outer_whitespace(content: str, original: str | None) -> str:
    if not original:
        return content
    leading_size = len(original) - len(original.lstrip())
    trailing_size = len(original) - len(original.rstrip())
    leading = original[:leading_size]
    trailing = original[-trailing_size:] if trailing_size else ""
    return f"{leading}{content}{trailing}"


@dataclass(slots=True)
class AgentRunSpec:
    """Configuration for a single agent execution."""

    initial_messages: list[dict[str, Any]] | None
    tools: ToolRegistry
    runtime: LLMRuntime
    max_iterations: int
    max_tool_result_chars: int
    transcript_input: TranscriptInput | None = None
    transcript_builder: TranscriptBuilder | None = None
    hook: AgentHook | None = None
    error_message: str | None = _DEFAULT_ERROR_MESSAGE
    max_iterations_message: str | None = None
    concurrent_tools: bool = False
    workspace: Path | None = None
    session_key: str | None = None
    provider_retry_mode: str = "standard"
    checkpoint_callback: CheckpointCallback | None = None
    consolidate_history: HistoryConsolidator | None = None
    consolidate_provider_compaction: ProviderCompactionConsolidator | None = None
    injection_callback: InjectionCallback | None = None
    terminal_injection_callback: InjectionCallback | None = None
    continuation_callback: ContinuationCallback | None = None
    finalize_on_max_iterations: bool = True
    provider_state: ProviderConversationState | None = None
    llm_usage_source: LLMUsageSource | None = None
    events: EventSink = NO_EVENTS


@dataclass(slots=True)
class AgentRunResult:
    """Outcome of a shared agent execution."""

    final_content: str | None
    messages: list[dict[str, Any]]
    tools_used: list[str] = field(default_factory=list)
    usage: LLMUsage | None = None
    # One entry per runner-visible model round. Recovery dispatches needed to
    # produce that round's response are folded into the same usage value.
    round_usages: list[LLMUsage] = field(default_factory=list)
    stop_reason: str = "completed"
    error: str | None = None
    failure_error_kind: str | None = None
    tool_events: list[dict[str, str]] = field(default_factory=list)
    had_injections: bool = False
    # Unstreamed terminal content or tail; excludes any prefix already delivered.
    pending_stream_content: str | None = None
    provider_state: ProviderConversationState | None = field(default=None, repr=False)
    summary_checkpoint: SessionSummaryCheckpoint | None = field(default=None, repr=False)
    provider_compaction_applied: bool = field(default=False, repr=False)


class AgentRunner:
    """Run a tool-capable LLM loop without product-layer concerns."""

    def __init__(self) -> None:
        self.context_governor = ContextGovernor()

    async def prepare_prompt(
        self, operation: Callable[_PromptArgs, _PromptResult],
        *args: _PromptArgs.args, **kwargs: _PromptArgs.kwargs,
    ) -> _PromptResult:
        """Share the bounded context worker for prompt filesystem preparation."""
        return await self.context_governor.prepare_in_background(operation, *args, **kwargs)

    async def _run_context_snapshot(
        self, hook: AgentHook, messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not messages or not hook.has_run_hooks():
            return []
        return await asyncio.to_thread(deepcopy, messages)

    @staticmethod
    def _append_injected_messages(
        messages: list[dict[str, Any]],
        injections: list[dict[str, Any]],
    ) -> None:
        """Append injected messages without rewriting the raw transcript."""
        messages.extend(injections)

    async def _try_drain_injections(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        *,
        phase: str,
        terminal: bool = False,
    ) -> bool:
        injections = await self._drain_injections(spec, terminal=terminal)
        if not injections:
            return False
        self._append_injected_messages(messages, injections)
        preview = "[content hidden]"
        if tool_log_content_allowed():
            preview = "\n\n".join(
                content for message in injections
                if isinstance(content := message.get("content"), str)
                and not is_hidden_history_message(message)
            )
            preview = preview[:80] + "..." if len(preview) > 80 else preview
        logger.info(
            "Injected {} follow-up message(s) {}: {}",
            len(injections), phase, preview,
        )
        return True

    @staticmethod
    async def _continuation_prompt(spec: AgentRunSpec) -> str | None:
        prompt = await spec.continuation_callback() if spec.continuation_callback is not None else None
        _raise_if_cancelling()
        return prompt

    async def _drain_injections(
        self,
        spec: AgentRunSpec,
        *,
        terminal: bool = False,
    ) -> list[dict[str, Any]]:
        callback = (
            spec.terminal_injection_callback
            if terminal
            else spec.injection_callback
        )
        if callback is None:
            return []
        try:
            items = await callback()
        except ExecutionControlError:
            raise
        except Exception:
            logger.opt(exception=tool_log_content_allowed()).error("injection_callback failed")
            return []
        if not items:
            return []
        injected_messages: list[dict[str, Any]] = []
        for item in items:
            if item is None:
                continue
            if isinstance(item, dict):
                message_item = cast(dict[str, Any], item)
                if message_item.get("role") == "user" and "content" in message_item:
                    if self._has_injection_content(message_item.get("content")):
                        injected_messages.append(message_item)
                continue
            content = getattr(item, "content") if hasattr(item, "content") else str(item)
            if self._has_injection_content(content):
                injected_messages.append({"role": "user", "content": content})
        return injected_messages

    @staticmethod
    def _has_injection_content(content: Any) -> bool:
        if content is None:
            return False
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            return bool(cast(list[Any], content))
        return True

    async def run(self, spec: AgentRunSpec) -> AgentRunResult:
        hook = spec.hook or AgentHook()
        has_run_hooks = hook.has_run_hooks()
        messages: list[dict[str, Any]] = []
        context = AgentRunHookContext(messages=[])
        llm_usage_source_token = bind_llm_usage_source(
            spec.llm_usage_source or source_from_session_key(spec.session_key)
        )

        try:
            try:
                try:
                    messages, compaction = await self.prepare_prompt(self._initial_transcript_and_compaction, spec)
                    context.messages = await self._run_context_snapshot(hook, messages) if has_run_hooks else []
                    await hook.before_run(context)
                    result = await self._run_core(spec, hook, messages, compaction)
                except Exception as exc:
                    context.messages = await self._run_context_snapshot(hook, messages) if has_run_hooks else []
                    context.stop_reason = "error"
                    context.error = f"Error: {type(exc).__name__}: {exc}"
                    context.exception = exc
                    await hook.on_error(context)
                    raise
                else:
                    context.messages = await self._run_context_snapshot(hook, result.messages) if has_run_hooks else []
                    context.final_content = result.final_content
                    context.tools_used = list(result.tools_used)
                    context.usage = result.usage
                    context.stop_reason = result.stop_reason
                    context.error = result.error
                    context.tool_events = deepcopy(result.tool_events)
                    context.had_injections = result.had_injections
                    context.exception = None
                    if context.error is not None:
                        await hook.on_error(context)
                    await hook.after_run(context)
                    return result
            except asyncio.CancelledError as exc:
                context.stop_reason = "cancelled"
                context.error = None
                context.exception = exc
                raise
            finally:
                if has_run_hooks:
                    try:
                        if isinstance(context.exception, asyncio.CancelledError):
                            context.messages = await self._run_context_snapshot(hook, messages)
                        else:
                            context.messages = await self._run_context_snapshot(hook, messages)
                    except asyncio.CancelledError as exc:
                        context.stop_reason = "cancelled"
                        context.error = None
                        context.exception = exc
                        context.messages = await self._run_context_snapshot(hook, messages)
                        raise
        finally:
            try:
                if context.exception is None:
                    await hook.on_finally(context)
                else:
                    try:
                        await hook.on_finally(context)
                    except Exception:
                        logger.opt(exception=tool_log_content_allowed()).error(
                            "AgentHook.on_finally error after {}",
                            context.stop_reason or "run exception",
                        )
            finally:
                reset_llm_usage_source(llm_usage_source_token)

    @staticmethod
    def _initial_transcript_and_compaction(
        spec: AgentRunSpec,
    ) -> tuple[list[dict[str, Any]], ContextCompactionState]:
        """Build the initial transcript and its compaction state."""
        consolidate_history = spec.consolidate_history
        if consolidate_history is None:
            raise ValueError("consolidate_history is required")
        transcript_input = spec.transcript_input
        if transcript_input is not None:
            if spec.initial_messages is not None:
                raise ValueError("provide either transcript_input or initial_messages, not both")
            transcript_builder = spec.transcript_builder
            if transcript_builder is None:
                raise ValueError("transcript_builder is required with transcript_input")
            return ContextCompactionState.from_transcript(
                transcript_input,
                transcript_builder,
                consolidate_history,
                spec.consolidate_provider_compaction,
            )
        if spec.initial_messages is None:
            raise ValueError("initial_messages is required without transcript_input")
        messages = list(spec.initial_messages)
        return messages, ContextCompactionState.from_messages(
            messages,
            consolidate_history,
            spec.consolidate_provider_compaction,
        )

    async def _run_core(
        self,
        spec: AgentRunSpec,
        hook: AgentHook,
        messages: list[dict[str, Any]],
        compaction: ContextCompactionState,
    ) -> AgentRunResult:
        final_content: str | None = None
        tools_used: list[str] = []
        usage: LLMUsage | None = None
        round_usages: list[LLMUsage] = []
        error: str | None = None
        failure_error_kind: str | None = None
        stop_reason = "completed"
        tool_events: list[dict[str, str]] = []
        external_lookup_counts: dict[str, int] = {}
        workspace_violation_counts: dict[str, int] = {}
        empty_content_retries = 0
        # Segments from one uninterrupted length-recovery chain. Tool work or
        # injected user input starts a new logical answer and clears the chain.
        length_recovery_parts: list[str] = []
        pending_length_segment: tuple[AgentHookContext, str] | None = None
        had_injections = False
        pending_stream_content: str | None = None

        async def checkpoint_compaction(state: ProviderConversationState) -> None:
            await self._emit_checkpoint(spec, {
                "phase": "model_input",
                "iteration": iteration,
                "model": spec.runtime.model,
                "assistant_message": None,
                "completed_tool_results": [],
                "pending_tool_calls": [],
                "provider_state": state,
            }, messages)

        conversation_state = ProviderConversationStateController(
            provider=spec.runtime.provider,
            model=spec.runtime.model,
            messages=messages,
            state=spec.provider_state,
            session_id=spec.session_key,
            checkpoint_callback=checkpoint_compaction,
        )
        governance_config = ContextGovernanceConfig(
            provider=spec.runtime.provider,
            model=spec.runtime.model,
            tools=spec.tools,
            workspace=spec.workspace,
            session_key=spec.session_key,
            max_tool_result_chars=spec.max_tool_result_chars,
            context_window_tokens=spec.runtime.context_window_tokens,
            max_tokens=spec.runtime.generation.max_tokens,
        )
        request_state = ModelRequestState(
            config=governance_config,
            conversation=conversation_state,
            compaction=compaction,
            events=spec.events,
        )

        async def end_length_segment(*, interrupted: bool) -> None:
            nonlocal pending_length_segment
            if pending_length_segment is None:
                return
            segment_context, segment_content = pending_length_segment
            pending_length_segment = None
            if interrupted:
                length_recovery_parts.clear()
            else:
                messages.append(build_length_recovery_message(segment_content))
            if hook.wants_streaming():
                segment_context.stream_continues_current_message = not interrupted
                await hook.on_stream_end(segment_context, resuming=True)

        iteration = -1
        followup_requested = False
        while (
            iteration + 1 < spec.max_iterations
            or followup_requested
            or await self._continuation_prompt(spec) is not None
        ):
            iteration += 1
            # A response boundary already admitted its follow-up request. Do not
            # reread continuation state for that same decision at loop entry.
            followup_requested = False
            # A resumed iteration must not inherit a previous iteration's failure.
            stop_reason = "completed"
            error = None
            # The session inbox cuts a finite snapshot before every model call.
            # This includes follow-ups that arrived before the first request and
            # messages received while the previous request or tools were running.
            drained_before_request = await self._try_drain_injections(
                spec, messages, phase="before model call",
            )
            if drained_before_request:
                had_injections = True
            await end_length_segment(interrupted=drained_before_request)
            context = AgentHookContext(
                iteration=iteration,
                messages=messages,
                session_key=spec.session_key,
            )
            await hook.before_iteration(context)
            request_message_count = len(messages)
            request_messages = await self.prepare_prompt(
                request_state.compaction.request_messages, messages,
            )
            request_state.recent_round_usages.append(None)
            response, raw_usage = await self._request_model(
                spec,
                request_messages,
                hook,
                context,
                request_state=request_state,
                transcript=messages,
            )
            assert request_state.messages is not None
            messages_for_model = request_state.messages
            conversation_state.observe_response(response, messages)
            await self.context_governor.accept_request(
                request_state, messages_for_model,
                raw_boundary=request_message_count,
            )
            context.response = response
            context.tool_calls = list(response.tool_calls)

            original_content = response.content
            reasoning_text, cleaned_content = extract_reasoning(
                response.reasoning_content,
                response.thinking_blocks,
                response.content,
            )
            response.content = cleaned_content
            round_usages.append(raw_usage)
            context.usage = raw_usage
            usage = self._merge_usage(usage, raw_usage)
            if reasoning_text and not context.streamed_reasoning:
                await hook.emit_reasoning(reasoning_text)
                await hook.emit_reasoning_end()
                context.streamed_reasoning = True

            if response.should_execute_tools:
                context.tool_calls = list(response.tool_calls)
                if hook.wants_streaming():
                    await hook.on_stream_end(context, resuming=True)

                assistant_message = build_assistant_message(
                    response.content or "",
                    tool_calls=[tc.to_openai_tool_call() for tc in response.tool_calls],
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                assistant_message = conversation_state.project_response_message(
                    assistant_message,
                    response,
                )
                messages.append(assistant_message)
                await self._emit_checkpoint(
                    spec,
                    {
                        "phase": "awaiting_tools",
                        "iteration": iteration,
                        "model": spec.runtime.model,
                        "assistant_message": assistant_message,
                        "completed_tool_results": [],
                        "pending_tool_calls": [tc.to_openai_tool_call() for tc in response.tool_calls],
                    },
                    messages,
                )

                await hook.before_execute_tools(context)

                async def settle_tool_results(completed: list[ToolCallResult]) -> None:
                    tool_events.extend(entry.event for entry in completed)
                    tools_used.extend(
                        entry.tool_call.name for entry in completed
                        if entry.event.get("status") == "ok"
                    )
                    context.tool_results = [entry.result for entry in completed]
                    context.tool_events = [entry.event for entry in completed]
                    completed_by_id = {entry.tool_call.id: entry for entry in completed}
                    interrupted = len(completed) != len(response.tool_calls)
                    completed_tool_results: list[dict[str, Any]] = []
                    for tool_call in response.tool_calls:
                        entry = completed_by_id.get(tool_call.id)
                        tool_message: dict[str, Any] = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                        }
                        if entry is not None:
                            tool_message["content"] = self.context_governor.normalize_tool_result(
                                governance_config,
                                tool_call.id,
                                tool_call.name,
                                entry.result,
                            )
                        else:
                            # Close interrupted calls as recovery does, without
                            # inventing a result or permitting an implicit retry.
                            tool_message["content"] = (
                                "Error: Task interrupted; this tool's outcome is unknown. "
                                "Check its effects before retrying."
                            )
                            tool_message["_recovery_interrupted"] = True
                        messages.append(tool_message)
                        completed_tool_results.append(tool_message)
                    checkpoint_model_messages = (
                        await self.prepare_prompt(
                            self.context_governor.prepare_messages_for_model, governance_config,
                            messages,
                        )
                        if response.provider_state is not None and not interrupted
                        else None
                    )
                    await self._emit_checkpoint(
                        spec,
                        {
                            "phase": "tools_completed",
                            "iteration": iteration,
                            "model": spec.runtime.model,
                            "assistant_message": assistant_message,
                            "completed_tool_results": completed_tool_results,
                            "pending_tool_calls": [],
                            "provider_state": conversation_state.checkpoint(
                                messages,
                                model_messages=checkpoint_model_messages,
                            ) if not interrupted else None,
                        },
                        messages,
                    )

                await execute_tool_calls(
                    spec.tools,
                    response.tool_calls,
                    concurrent=spec.concurrent_tools,
                    external_lookup_counts=external_lookup_counts,
                    workspace_violation_counts=workspace_violation_counts,
                    hook=hook,
                    context=context,
                    model_messages=messages_for_model,
                    compacted_tool_results=request_state.compacted_tool_results,
                    on_settled=settle_tool_results,
                )
                empty_content_retries = 0
                length_recovery_parts.clear()
                await hook.after_iteration(context)
                continue

            if response.has_tool_calls:
                logger.warning(
                    "Ignoring tool calls under finish_reason='{}' for {}",
                    response.finish_reason,
                    spec.session_key or "default",
                )

            clean = hook.finalize_content(context, response.content)
            if (
                response.finish_reason
                not in {"error", "length", "refusal", "content_filter"}
                and is_blank_text(clean)
            ):
                empty_content_retries += 1
                if empty_content_retries < _MAX_EMPTY_RETRIES:
                    logger.warning(
                        "Empty response on turn {} for {} ({}/{}); retrying",
                        iteration,
                        spec.session_key or "default",
                        empty_content_retries,
                        _MAX_EMPTY_RETRIES,
                    )
                    if hook.wants_streaming():
                        await hook.on_stream_end(context, resuming=False)
                    await hook.after_iteration(context)
                    continue
                logger.warning(
                    "Empty response on turn {} for {} after {} retries; attempting finalization",
                    iteration,
                    spec.session_key or "default",
                    empty_content_retries,
                )
                if hook.wants_streaming():
                    await hook.on_stream_end(context, resuming=False)
                request_state.recent_round_usages.append(None)
                response = await self._request_finalization_retry(
                    spec,
                    messages_for_model,
                    request_state=request_state,
                    transcript=messages,
                )
                retry_usage = await self._record_request_usage(spec, request_state, response)
                round_usages.append(retry_usage)
                usage = self._merge_usage(usage, retry_usage)
                raw_usage = self._merge_usage(raw_usage, retry_usage)
                context.response = response
                context.usage = raw_usage
                context.tool_calls = list(response.tool_calls)
                original_content = response.content
                clean = hook.finalize_content(context, response.content)

            if response.finish_reason == "length":
                if len(length_recovery_parts) < _MAX_LENGTH_RECOVERIES:
                    length_recovery_parts.append(
                        _restore_outer_whitespace(clean or "", original_content)
                    )
                    logger.info(
                        "Output truncated on turn {} for {} ({}/{}); continuing",
                        iteration,
                        spec.session_key or "default",
                        len(length_recovery_parts),
                        _MAX_LENGTH_RECOVERIES,
                    )
                    messages.append(conversation_state.project_response_message(
                        build_assistant_message(
                            clean,
                            reasoning_content=response.reasoning_content,
                            thinking_blocks=response.thinking_blocks,
                        ),
                        response,
                    ))
                    # The next input snapshot decides whether to continue this
                    # answer or close its stream before answering a new question.
                    pending_length_segment = (context, clean or "")
                    await hook.after_iteration(context)
                    continue

            # Some streaming providers recover with a complete response but no
            # content deltas. When an earlier length segment is already visible,
            # emit this terminal segment into the same stream; otherwise the
            # regular full response would duplicate the visible prefix.
            if (
                length_recovery_parts
                and hook.wants_streaming()
                and not context.streamed_content
                and response.finish_reason != "error"
                and not is_blank_text(clean)
            ):
                await hook.on_stream(
                    context,
                    _restore_outer_whitespace(clean or "", original_content),
                )
                context.streamed_content = True

            assistant_message: dict[str, Any] | None = None
            if response.finish_reason != "error" and not is_blank_text(clean):
                assistant_message = build_assistant_message(
                    clean,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                assistant_message = conversation_state.project_response_message(
                    assistant_message,
                    response,
                )
                messages.append(assistant_message)
                await self._emit_checkpoint(
                    spec,
                    {
                        "phase": "final_response",
                        "iteration": iteration,
                        "model": spec.runtime.model,
                        "assistant_message": assistant_message,
                        "completed_tool_results": [],
                        "pending_tool_calls": [],
                        "provider_state": conversation_state.checkpoint(messages),
                    },
                    messages,
                )

            if response.finish_reason == "error":
                interrupted_parts = [
                    content
                    for part in context.streamed_content_parts
                    if (content := extract_reasoning(None, None, part)[1])
                ]
                interrupted_content = hook.finalize_content(
                    context, "\n\n".join(interrupted_parts),
                )
                if not is_blank_text(interrupted_content):
                    # This is unsynchronized output, not a completed response or
                    # provider-owned projection. Keep it in the next native delta.
                    messages.append({
                        **build_assistant_message(interrupted_content),
                        "_interrupted": True,
                    })

            # Check for mid-turn injections BEFORE signaling stream end.
            # If injections are found we keep the stream alive (resuming=True)
            # so streaming channels don't prematurely finalize the card.
            normal_response = (
                assistant_message is not None
                and response.finish_reason not in {"error", "length", "refusal", "content_filter"}
            )
            ordinary_budget_remaining = iteration + 1 < spec.max_iterations
            continuation_prompt = None
            if normal_response and not ordinary_budget_remaining:
                continuation_prompt = await self._continuation_prompt(spec)
            can_make_followup_request = ordinary_budget_remaining or continuation_prompt is not None
            should_continue = can_make_followup_request and await self._try_drain_injections(
                spec, messages, phase="after final response",
            )
            if not should_continue and normal_response:
                if ordinary_budget_remaining:
                    continuation_prompt = await self._continuation_prompt(spec)
                if continuation_prompt is not None:
                    messages.append({
                        "role": "user", "content": continuation_prompt,
                        HIDDEN_HISTORY_META: {"kind": "internal_continuation"},
                    })
                    should_continue = True
                    logger.info("Injected caller-requested continuation after final response")
                elif can_make_followup_request:
                    should_continue = await self._try_drain_injections(
                        spec, messages, phase="at terminal response", terminal=True,
                    )
            if should_continue:
                had_injections = True

            if hook.wants_streaming():
                await hook.on_stream_end(context, resuming=should_continue)

            if should_continue:
                followup_requested = True
                length_recovery_parts.clear()
                await hook.after_iteration(context)
                continue

            if response.finish_reason == "error":
                if LLMProvider.is_arrearage_response(response):
                    final_content = _ARREARAGE_ERROR_MESSAGE
                else:
                    final_content = clean or spec.error_message or _DEFAULT_ERROR_MESSAGE
                stop_reason = "error"
                error = final_content
                self._append_model_error_placeholder(messages)
                context.final_content = final_content
                context.error = error
                context.stop_reason = stop_reason
                await hook.after_iteration(context)
                if can_make_followup_request and await self._try_drain_injections(
                    spec, messages, phase="after LLM error",
                ):
                    had_injections = True
                    length_recovery_parts.clear()
                    continue
                failure_error_kind = LLMProvider.public_error_kind(response)
                break
            if is_blank_text(clean):
                final_content = EMPTY_FINAL_RESPONSE_MESSAGE
                stop_reason = "empty_final_response"
                error = final_content
                self._append_final_message(messages, final_content)
                context.final_content = final_content
                context.error = error
                context.stop_reason = stop_reason
                await hook.after_iteration(context)
                if can_make_followup_request and await self._try_drain_injections(
                    spec, messages, phase="after empty response",
                ):
                    had_injections = True
                    length_recovery_parts.clear()
                    continue
                break

            if length_recovery_parts:
                final_content = (
                    "".join(length_recovery_parts)
                    + _restore_outer_whitespace(clean or "", original_content)
                ).strip()
            else:
                final_content = clean
            context.final_content = final_content
            context.stop_reason = stop_reason
            await hook.after_iteration(context)
            break
        else:
            await end_length_segment(interrupted=False)
            stop_reason = "max_iterations"
            # Once a goal allowed tool work beyond the ordinary budget, its
            # closure deserves an answer, not a claim that work is unfinished.
            goal_overrun = iteration + 1 > spec.max_iterations
            terminal_content = None
            if spec.finalize_on_max_iterations:
                terminal_content, usage = await self._try_finalize_after_max_iterations(
                    spec,
                    hook,
                    messages,
                    usage,
                    iteration=iteration + 1,
                    request_state=request_state,
                    round_usages=round_usages,
                )
            if terminal_content is not None and goal_overrun:
                stop_reason = "completed"
                pending_stream_content = terminal_content
            if terminal_content is None:
                if goal_overrun and spec.finalize_on_max_iterations:
                    terminal_content = EMPTY_FINAL_RESPONSE_MESSAGE
                    stop_reason = "empty_final_response"
                    error = terminal_content
                    pending_stream_content = terminal_content
                else:
                    terminal_content = self._max_iterations_fallback(spec)
            if length_recovery_parts:
                terminal_tail = f"\n\n{terminal_content.lstrip()}"
                final_content = (
                    "".join(length_recovery_parts).rstrip() + terminal_tail
                ).strip()
                pending_stream_content = terminal_tail
            else:
                final_content = terminal_content
            self._append_final_message(messages, terminal_content)

        return AgentRunResult(
            final_content=final_content,
            messages=messages,
            tools_used=tools_used,
            usage=usage,
            round_usages=round_usages,
            stop_reason=stop_reason,
            error=error,
            failure_error_kind=failure_error_kind,
            tool_events=tool_events,
            had_injections=had_injections,
            pending_stream_content=pending_stream_content,
            provider_state=conversation_state.finish(messages),
            summary_checkpoint=request_state.compaction.summary_checkpoint,
            provider_compaction_applied=request_state.provider_compaction_applied,
        )

    async def _prepare_model_request(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        request_state: ModelRequestState,
        transcript: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        messages, provider_context = await self.context_governor.prepare_request(
            request_state,
            messages,
            tool_definitions=tools,
            transcript=transcript,
        )
        generation = spec.runtime.generation
        return messages, {
            "messages": messages,
            "tools": tools,
            "model": spec.runtime.model,
            "retry_mode": spec.provider_retry_mode,
            "temperature": generation.temperature,
            "max_tokens": generation.max_tokens,
            "reasoning_effort": generation.reasoning_effort,
            "provider_context": replace(
                provider_context or ProviderCallContext(),
                response_preset=spec.runtime.model_preset or "",
            ),
        }

    async def _invoke_model(
        self, spec: AgentRunSpec, state: ModelRequestState, kwargs: dict[str, Any],
        *, record_timing: Callable[[LLMResponse], None] | None = None,
    ) -> LLMResponse:
        """Observe the logical provider invocation, after request preparation.

        Physical retries/fallbacks and provider-internal pre-request compaction
        remain inside the call. Post-return compaction summarization is outside.
        Only provider-returned usage is published here, never estimated zeros.
        Callers reserve a live round slot; recovery invocations update it.
        """
        request_id = uuid4().hex
        request_usage: LLMUsage | None = None

        async def emit(phase: Literal["started", "completed", "failed", "cancelled"]) -> None:
            state.request_sequence += 1
            if not spec.events.accepts(ModelRequestEvent):
                return
            await spec.events.emit(ModelRequestEvent(
                request_id=request_id, run_id=state.request_run_id,
                sequence=state.request_sequence, phase=phase,
                usage=state.request_usage,
                round_usages=tuple(usage for usage in state.recent_round_usages if usage is not None),
                context_window_tokens=spec.runtime.context_window_tokens,
                request_usage=request_usage,
            ))

        try:
            if spec.hook is not None:
                await spec.hook.before_model_request()
            await emit("started")
            _raise_if_cancelling()
            response = await spec.runtime.provider.chat_stream_with_retry(**kwargs)
            _raise_if_cancelling()
        except asyncio.CancelledError:
            try:
                await shield_and_drain(emit("cancelled"))
            except asyncio.CancelledError:
                pass
            raise
        except Exception:
            await emit("failed")
            raise
        if record_timing is not None:
            record_timing(response)
        if response.usage is not None:
            reported_usage = response.usage.with_timing(
                generation_ms=response.generation_ms, ttft_ms=response.ttft_ms,
            )
            request_usage = reported_usage
            state.request_usage = self._merge_usage(state.request_usage, reported_usage)
            state.recent_round_usages[-1] = self._merge_usage(
                state.recent_round_usages[-1], reported_usage,
            )
        del state.recent_round_usages[:-8]
        await emit("failed" if response.finish_reason == "error" else "completed")
        return response

    async def _request_model(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        hook: AgentHook,
        context: AgentHookContext,
        *,
        request_state: ModelRequestState,
        malformed_retry: bool = False,
        transcript: list[dict[str, Any]] | None,
    ) -> tuple[LLMResponse, LLMUsage]:
        _raise_if_cancelling()
        messages, kwargs = await self._prepare_model_request(
            spec,
            messages,
            tools=spec.tools.get_definitions(),
            request_state=request_state,
            transcript=transcript,
        )
        _raise_if_cancelling()
        wants_streaming = hook.wants_streaming()

        active_hosted_tools: dict[str, dict[str, Any]] = {}
        native_reasoning_open = False
        native_reasoning_close_task: asyncio.Task[None] | None = None
        request_started_at = 0.0
        first_output_at: float | None = None
        generation_started_at: float | None = None
        generation_elapsed_s = 0.0
        stream_buf = ""

        def _end_stream_segment() -> None:
            nonlocal stream_buf
            if stream_buf:
                context.streamed_content_parts.append(stream_buf)
                stream_buf = ""

        def _generation_delta(delta: str) -> None:
            nonlocal first_output_at, generation_started_at
            if not delta:
                return
            now = time.perf_counter()
            if first_output_at is None:
                first_output_at = now
            if generation_started_at is None:
                generation_started_at = now

        def _pause_generation() -> None:
            nonlocal generation_elapsed_s, generation_started_at
            if generation_started_at is None:
                return
            generation_elapsed_s += max(0.0, time.perf_counter() - generation_started_at)
            generation_started_at = None

        async def _close_native_reasoning() -> None:
            nonlocal native_reasoning_open, native_reasoning_close_task
            if native_reasoning_close_task is None:
                if not native_reasoning_open:
                    return
                native_reasoning_open = False
                native_reasoning_close_task = asyncio.create_task(
                    hook.emit_reasoning_end()
                )

            close_task = native_reasoning_close_task
            cancellation: asyncio.CancelledError | None = None
            while not close_task.done():
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError as exc:
                    cancellation = cancellation or exc
            try:
                close_task.result()
            finally:
                if native_reasoning_close_task is close_task:
                    native_reasoning_close_task = None
            if cancellation is not None:
                raise cancellation

        async def _provider_tool_event(event: dict[str, Any]) -> None:
            if event.get("kind") != "hosted_tool":
                return
            await _close_native_reasoning()
            if event.get("phase") == "start":
                _end_stream_segment()
            await hook.on_provider_tool_event(context, event)
            call_id = event.get("call_id")
            if not call_id:
                return
            call_id = str(call_id)
            if event.get("phase") == "start":
                active_hosted_tools[call_id] = dict(event)
            elif event.get("phase") in {"end", "error"}:
                active_hosted_tools.pop(call_id, None)

        if wants_streaming:
            thinking_buf = ""

            async def _stream(delta: str) -> None:
                nonlocal stream_buf
                stream_buf += delta
                _generation_delta(delta)
                if delta:
                    context.streamed_content = True
                    await _close_native_reasoning()
                await hook.on_stream(context, delta)

            async def _thinking(delta: str) -> None:
                nonlocal native_reasoning_open, thinking_buf
                if not delta:
                    return
                _generation_delta(delta)
                prev_clean = strip_reasoning_tags(thinking_buf)
                thinking_buf += delta
                new_clean = strip_reasoning_tags(thinking_buf)
                incremental = new_clean[len(prev_clean):]
                if incremental:
                    context.streamed_reasoning = True
                    native_reasoning_open = True
                    await hook.emit_reasoning(incremental)

            async def _stream_recover() -> None:
                _pause_generation()
                await _close_native_reasoning()
                _end_stream_segment()
                await hook.on_stream_end(context, resuming=True)

            kwargs.update(
                on_content_delta=_stream,
                on_thinking_delta=_thinking,
                on_tool_call_delta=_provider_tool_event,
                on_stream_recover=_stream_recover,
            )
        def record_timing(response: LLMResponse) -> None:
            _pause_generation()
            if first_output_at is not None:
                response.ttft_ms = max(0, round((first_output_at - request_started_at) * 1000))
            if generation_elapsed_s > 0:
                response.generation_ms = max(1, round(generation_elapsed_s * 1000))

        coro = self._invoke_model(spec, request_state, kwargs, record_timing=record_timing)

        # Providers bound the wait for each stream event, including reasoning and tool deltas.
        request_started_at = time.perf_counter()
        try:
            response = await coro
            _raise_if_cancelling()
        except asyncio.CancelledError:
            _pause_generation()
            await _close_native_reasoning()
            raise
        _pause_generation()
        await _close_native_reasoning()
        _end_stream_segment()
        await self.context_governor.summarize_provider_compaction(
            request_state,
            response,
            current_request_boundary=(len(transcript) if transcript is not None else None),
        )
        request_state.provider_compaction_applied |= response.provider_compaction_applied
        round_usage = await self._record_request_usage(spec, request_state, response)
        # chat_stream_with_retry may recover internally, so only fail unfinished
        # hosted calls after the provider returns its final error response.
        if response.finish_reason == "error":
            for event in list(active_hosted_tools.values()):
                await _provider_tool_event({
                    **event,
                    "phase": "error",
                    "result": None,
                    "error": response.content
                    or "Model request failed before the provider-hosted tool completed.",
                })
        dropped, all_dropped, original_finish_reason = (
            self._drop_malformed_tool_calls(response)
        )
        if (
            all_dropped
            and original_finish_reason in ("tool_calls", "function_call")
            and not malformed_retry
        ):
            logger.warning(
                "Retrying LLM request after all {} malformed tool call(s) were dropped",
                dropped,
            )
            retry_messages = self._malformed_tool_call_retry_messages(
                messages, response.content,
            )
            retry_response, retry_usage = await self._request_model(
                spec, retry_messages, hook, context,
                request_state=request_state,
                malformed_retry=True,
                transcript=None,
            )
            return retry_response, round_usage + retry_usage
        if (
            all_dropped
            and original_finish_reason in ("tool_calls", "function_call")
            and malformed_retry
        ):
            logger.warning(
                "Malformed tool calls persisted after retry; falling back to no-tools request",
            )
            fallback_messages = self._malformed_tool_call_retry_messages(
                messages, response.content,
            )
            fallback_response = await self._request_no_tools(
                spec,
                fallback_messages,
                request_state=request_state,
            )
            fallback_usage = await self._record_request_usage(
                spec,
                request_state,
                fallback_response,
            )
            return fallback_response, round_usage + fallback_usage
        return response, round_usage

    @staticmethod
    def _drop_malformed_tool_calls(
        response: LLMResponse,
    ) -> tuple[int, bool, str | None]:
        """Strip tool calls whose name is missing/non-string from the response.

        Returns (dropped_count, all_dropped, original_finish_reason).

        A degenerate call (name=None or "") cannot be executed, and if it were
        persisted into the assistant message it would be replayed on every
        subsequent turn, causing upstream validation errors
        (``tool_use.name: Input should be a valid string``) that permanently
        wedge the session. Dropping it here keeps it out of execution, the
        assistant message, and the saved history in one place.
        """
        calls = getattr(response, "tool_calls", None)
        if not calls:
            return (0, False, getattr(response, "finish_reason", None))
        valid = [tc for tc in calls if tc.has_valid_name()]
        if len(valid) == len(calls):
            return (0, False, getattr(response, "finish_reason", None))
        dropped = len(calls) - len(valid)
        original_finish_reason = getattr(response, "finish_reason", None)
        logger.warning(
            "Dropped {} malformed tool call(s) with missing/non-string name "
            "from LLM response (finish_reason={!r})",
            dropped,
            original_finish_reason,
        )
        response.tool_calls = valid
        # The opaque candidate still contains every raw function_call item.
        # Advancing it after dropping even one call would replay an unmatched
        # call without a corresponding tool output on the next request.
        response.provider_state = None
        if not valid and original_finish_reason in ("tool_calls", "function_call"):
            response.finish_reason = "stop"
        return (dropped, not valid, original_finish_reason)

    @staticmethod
    def _malformed_tool_call_retry_messages(
        messages: list[dict[str, Any]],
        assistant_text: str | None,
    ) -> list[dict[str, Any]]:
        retry_messages = list(messages)
        note = (
            "The previous model response attempted to call tools, but every tool call "
            "was malformed: the tool_use blocks had missing or non-string tool names. "
            "Do not answer with a promise to use tools. Either call the required tools again "
            "using valid tool names from the provided tool list and JSON object inputs, or give "
            "a final answer only if no tool is required."
        )
        if assistant_text:
            note += (
                f"\n\nPrevious assistant text before the malformed calls:\n"
                f"{assistant_text}"
            )
        retry_messages.append({"role": "user", "content": note})
        return retry_messages

    async def _request_finalization_retry(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        *,
        request_state: ModelRequestState,
        transcript: list[dict[str, Any]],
    ) -> LLMResponse:
        retry_messages = self._finalization_retry_messages(messages)
        response = await self._request_no_tools(
            spec,
            retry_messages,
            request_state=request_state,
            transcript=transcript,
        )
        request_state.conversation.observe_response(
            response,
            transcript,
            adopt_candidate_state=False,
        )
        return response

    @staticmethod
    def _finalization_retry_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        retry_messages = list(messages)
        retry_messages.append(build_finalization_retry_message())
        return retry_messages

    async def _try_finalize_after_max_iterations(
        self,
        spec: AgentRunSpec,
        hook: AgentHook,
        messages: list[dict[str, Any]],
        usage: LLMUsage | None,
        *,
        iteration: int,
        request_state: ModelRequestState,
        round_usages: list[LLMUsage],
    ) -> tuple[str | None, LLMUsage | None]:
        compaction = request_state.compaction
        request_messages = await self.prepare_prompt(compaction.request_messages, messages)
        retry_messages = (
            self._finalization_retry_messages(request_messages)
            if iteration > spec.max_iterations
            else self._budget_exhausted_finalization_messages(request_messages)
        )
        request_state.recent_round_usages.append(None)
        try:
            response = await self._request_no_tools(
                spec,
                retry_messages,
                request_state=request_state,
                transcript=messages,
            )
        except ProviderStateCommitError:
            raise
        except Exception:
            logger.opt(exception=tool_log_content_allowed()).error(
                "Budget-exhausted finalization failed for {}; using fallback",
                spec.session_key or "default",
            )
            return None, usage

        raw_usage = await self._record_request_usage(spec, request_state, response)
        round_usages.append(raw_usage)
        usage = self._merge_usage(usage, raw_usage)
        if response.finish_reason == "error" or response.has_tool_calls:
            logger.warning(
                "Budget-exhausted finalization returned finish_reason='{}' "
                "with {} tool call(s) for {}; using fallback",
                response.finish_reason,
                len(response.tool_calls),
                spec.session_key or "default",
            )
            return None, usage

        context = AgentHookContext(
            iteration=iteration,
            messages=messages,
            response=response,
            usage=raw_usage,
            session_key=spec.session_key,
        )
        clean = hook.finalize_content(context, response.content)
        if is_blank_text(clean):
            return None, usage
        return clean, usage

    async def _request_no_tools(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        *,
        request_state: ModelRequestState,
        transcript: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        _raise_if_cancelling()
        _, kwargs = await self._prepare_model_request(
            spec,
            messages,
            tools=None,
            request_state=request_state,
            transcript=transcript,
        )
        _raise_if_cancelling()
        response = await self._invoke_model(spec, request_state, kwargs)
        _raise_if_cancelling()
        await self.context_governor.summarize_provider_compaction(
            request_state,
            response,
            current_request_boundary=(len(transcript) if transcript is not None else None),
        )
        _raise_if_cancelling()
        request_state.provider_compaction_applied |= response.provider_compaction_applied
        return response

    @staticmethod
    def _budget_exhausted_finalization_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        retry_messages = list(messages)
        retry_messages.append(build_budget_exhausted_finalization_message())
        return retry_messages

    @staticmethod
    def _max_iterations_fallback(spec: AgentRunSpec) -> str:
        if spec.max_iterations_message:
            return spec.max_iterations_message.format(
                max_iterations=spec.max_iterations,
            )
        return render_template(
            "agent/max_iterations_message.md",
            strip=True,
            max_iterations=spec.max_iterations,
        )

    def _usage_or_estimate(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        response: LLMResponse,
        *,
        tool_definitions: list[dict[str, Any]] | None,
    ) -> LLMUsage:
        usage = response.usage
        if response.finish_reason == "error":
            if usage is None or usage.total_tokens == 0:
                usage = LLMUsage.empty_request()
        elif usage is None or usage.total_tokens == 0:
            usage = self._estimate_response_usage(
                spec,
                messages,
                response,
                tool_definitions=tool_definitions,
            )
        return usage.with_timing(
            generation_ms=response.generation_ms,
            ttft_ms=response.ttft_ms,
        )

    async def _record_request_usage(
        self,
        spec: AgentRunSpec,
        state: ModelRequestState,
        response: LLMResponse,
    ) -> LLMUsage:
        assert state.messages is not None
        if response.finish_reason != "error" and (
            response.usage is None or response.usage.total_tokens == 0
        ):
            usage = await self.prepare_prompt(
                self._usage_or_estimate, spec, state.messages, response,
                tool_definitions=state.tool_definitions,
            )
        else:
            usage = self._usage_or_estimate(
                spec, state.messages, response, tool_definitions=state.tool_definitions,
            )
        # A rewritten input or another model's count cannot bound the next request.
        state.usage = None if response.provider_compaction_applied or response.is_fallback else usage
        return usage

    def _estimate_response_usage(
        self,
        spec: AgentRunSpec,
        messages: list[dict[str, Any]],
        response: LLMResponse,
        *,
        tool_definitions: list[dict[str, Any]] | None,
    ) -> LLMUsage:
        prompt_tokens, _ = estimate_prompt_tokens_chain(
            spec.runtime.provider,
            spec.runtime.model,
            messages,
            tool_definitions,
        )
        assistant_message = build_assistant_message(
            response.content or "",
            tool_calls=[tc.to_openai_tool_call() for tc in response.tool_calls],
            reasoning_content=response.reasoning_content,
            thinking_blocks=response.thinking_blocks,
        )
        completion_tokens = estimate_message_tokens(assistant_message)
        return LLMUsage.estimated(
            input_tokens=max(0, prompt_tokens),
            output_tokens=max(0, completion_tokens),
        )

    @staticmethod
    def _merge_usage(
        left: LLMUsage | None,
        right: LLMUsage | None,
    ) -> LLMUsage | None:
        if left is None:
            return right
        if right is None:
            return left
        return left + right

    async def _emit_checkpoint(
        self,
        spec: AgentRunSpec,
        payload: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> None:
        callback = spec.checkpoint_callback
        if callback is not None:
            if spec.transcript_input is not None:
                start = spec.transcript_input.message_count
            else:
                assert spec.initial_messages is not None
                start = len(spec.initial_messages)
            # Replacing the checkpoint must retain every earlier round of this
            # run, including follow-ups consumed since the accepted input.
            batch_size = (
                0 if payload["phase"] == "model_input"
                else 1 + len(payload["completed_tool_results"])
            )
            await callback({
                **payload,
                "preceding_messages": messages[start:len(messages) - batch_size],
            })

    @staticmethod
    def _append_final_message(messages: list[dict[str, Any]], content: str | None) -> None:
        if not content:
            return
        if (
            messages
            and messages[-1].get("role") == "assistant"
            and not messages[-1].get("tool_calls")
        ):
            if messages[-1].get("content") == content:
                return
            messages[-1] = build_assistant_message(content)
            return
        messages.append(build_assistant_message(content))

    @staticmethod
    def _append_model_error_placeholder(messages: list[dict[str, Any]]) -> None:
        if messages and messages[-1].get("role") == "assistant" and not messages[-1].get("tool_calls"):
            return
        messages.append(build_assistant_message(_PERSISTED_MODEL_ERROR_PLACEHOLDER))
