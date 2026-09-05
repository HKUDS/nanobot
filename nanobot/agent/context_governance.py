"""Model-message governance and compaction for agent runner requests.

This module owns model-facing message shaping, request pressure, H/delta
compaction state, and tool-result content normalization. It may return copied
messages or persisted-result placeholders, but it must not mutate an existing
session history list in place.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from loguru import logger

from nanobot.agent.context import TranscriptInput
from nanobot.bus.outbound_events import (
    ContextCompactionCallback,
    ContextCompactionEvent,
    emit_context_compaction,
)
from nanobot.providers.base import (
    LLMResponse,
    LLMUsage,
    ProviderCallContext,
    ProviderConversationState,
)
from nanobot.providers.conversation_state import (
    ProviderConversationStateController,
    allows_conversation_message_merge,
)
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_MESSAGE_META,
    detach_runtime_context,
    reattach_runtime_context,
)
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.summary import (
    SUMMARY_CONTINUATION_TEXT,
    SessionSummaryCheckpoint,
)
from nanobot.utils.helpers import (
    estimate_message_tokens,
    estimate_prompt_tokens_chain,
    find_legal_message_start,
    maybe_persist_tool_result,
    truncate_text,
)
from nanobot.utils.runtime import ensure_nonempty_tool_result

if TYPE_CHECKING:
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.providers.base import LLMProvider

TranscriptBuilder = Callable[[TranscriptInput], list[dict[str, Any]]]
HistoryConsolidator = Callable[
    [list[dict[str, Any]], str | None],
    Awaitable[str | None],
]
ProviderCompactionConsolidator = Callable[
    [ProviderConversationState, list[dict[str, Any]], str | None],
    Awaitable[str | None],
]

SNIP_SAFETY_BUFFER = 1024
# read_file is the recovery path for persisted results; exempting it prevents persist->read->persist loops.
TOOL_RESULT_OFFLOAD_EXEMPT_TOOLS = frozenset({"read_file"})
BACKFILL_CONTENT = "[Tool result unavailable — call was interrupted or lost]"
PLACEHOLDER_TEXTS = frozenset({
    "[Previous assistant message omitted.]",
})


class ContextWindowExceededError(RuntimeError):
    """Raised before a locally fitted request that still exceeds its budget."""

    def __init__(
        self,
        *,
        session_key: str | None,
        estimated_tokens: int,
        input_budget: int,
        source: str,
    ) -> None:
        self.session_key = session_key
        self.estimated_tokens = estimated_tokens
        self.input_budget = input_budget
        self.source = source
        super().__init__(
            "Model input still exceeds the local context budget after request fitting "
            f"for {session_key or 'default'}: {estimated_tokens}/{input_budget} via {source}"
        )


def _tool_call_name_is_valid(tool_call: Any) -> bool:
    """Whether a persisted OpenAI-style tool_call carries a usable name.

    Mirrors ``ToolCallRequest.has_valid_name`` for the dict shape stored in
    message history: a degenerate call with ``name=None`` / ``""`` cannot be
    executed and is rejected by upstream APIs if replayed.
    """
    if not isinstance(tool_call, dict):
        return False
    tool_call_data = cast(dict[str, Any], tool_call)
    fn = tool_call_data.get("function")
    name = cast(dict[str, Any], fn).get("name") if isinstance(fn, dict) else tool_call_data.get("name")
    return isinstance(name, str) and bool(name)


@dataclass(slots=True)
class ContextGovernanceConfig:
    provider: LLMProvider
    model: str
    tools: ToolRegistry
    workspace: Path | None
    session_key: str | None
    max_tool_result_chars: int
    context_window_tokens: int | None = None
    context_block_limit: int | None = None
    max_tokens: int | None = None


@dataclass(slots=True)
class ContextCompactionState:
    """Track accepted provider input H separately from the unsent delta."""

    raw_messages: list[dict[str, Any]]
    accepted_messages: list[dict[str, Any]]
    raw_accepted_boundary: int
    active_summary: str | None
    transcript_input: TranscriptInput
    transcript_builder: TranscriptBuilder
    consolidate_history: HistoryConsolidator
    consolidate_provider_compaction: ProviderCompactionConsolidator | None
    summary_checkpoint: SessionSummaryCheckpoint | None = None

    @classmethod
    def from_transcript(
        cls,
        transcript_input: TranscriptInput,
        transcript_builder: TranscriptBuilder,
        consolidate_history: HistoryConsolidator | None,
        consolidate_provider_compaction: ProviderCompactionConsolidator | None,
    ) -> tuple[list[dict[str, Any]], ContextCompactionState | None]:
        """Build the raw transcript and its initial H/delta boundary."""
        messages = list(transcript_builder(transcript_input))
        if consolidate_history is None:
            return messages, None
        accepted_history_boundary = 1 + len(transcript_input.history)
        return messages, cls(
            raw_messages=messages,
            accepted_messages=deepcopy(messages[:accepted_history_boundary]),
            raw_accepted_boundary=accepted_history_boundary,
            active_summary=(
                transcript_input.session_summary["text"]
                if transcript_input.session_summary is not None
                else None
            ),
            transcript_input=transcript_input,
            transcript_builder=transcript_builder,
            consolidate_history=consolidate_history,
            consolidate_provider_compaction=consolidate_provider_compaction,
        )

    def request_messages(
        self,
        raw_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            *deepcopy(self.accepted_messages),
            *deepcopy(raw_messages[self.raw_accepted_boundary:]),
        ]

    def delta_after_accepted(
        self,
        request_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return deepcopy(request_messages[len(self.accepted_messages):])

    def accept_request(
        self,
        model_messages: list[dict[str, Any]],
        *,
        raw_boundary: int,
    ) -> None:
        """Advance H after the provider has received one request."""
        self.accepted_messages = deepcopy(model_messages)
        self.raw_accepted_boundary = raw_boundary


@dataclass(slots=True)
class ModelRequestState:
    """Context state shared by every provider request in one runner turn."""

    config: ContextGovernanceConfig
    conversation: ProviderConversationStateController
    usage: LLMUsage | None = None
    messages: list[dict[str, Any]] | None = None
    tool_definitions: list[dict[str, Any]] | None = None
    compaction: ContextCompactionState | None = None
    provider_compaction_applied: bool = False
    compaction_callback: ContextCompactionCallback | None = None


class ContextGovernor:
    """Own model-request context while preserving persisted history."""

    @staticmethod
    def _merge_message_content(left: Any, right: Any) -> str | list[dict[str, Any]]:
        if isinstance(left, str) and isinstance(right, str):
            return f"{left}\n\n{right}" if left else right

        def _to_blocks(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return [
                    cast(dict[str, Any], item)
                    if isinstance(item, dict)
                    else {"type": "text", "text": str(item)}
                    for item in cast(list[Any], value)
                ]
            if value is None:
                return []
            return [{"type": "text", "text": str(value)}]

        return _to_blocks(left) + _to_blocks(right)

    @classmethod
    def _merge_adjacent_user_messages_for_model(
        cls,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge adjacent visible user messages only in the model-facing copy."""
        prepared: list[dict[str, Any]] = []
        for source in messages:
            injection = deepcopy(source)
            if (
                prepared
                and injection.get("role") == "user"
                and prepared[-1].get("role") == "user"
                and injection.get("content") != SUMMARY_CONTINUATION_TEXT
                and prepared[-1].get("content") != SUMMARY_CONTINUATION_TEXT
                and not is_hidden_history_message(injection)
                and not is_hidden_history_message(prepared[-1])
                and allows_conversation_message_merge(injection)
                and allows_conversation_message_merge(prepared[-1])
            ):
                merged = dict(prepared[-1])
                left_meta = merged.get("_meta")
                right_meta = injection.get("_meta")
                left_meta_dict = (
                    cast(dict[str, Any], left_meta) if isinstance(left_meta, dict) else None
                )
                right_meta_dict = (
                    cast(dict[str, Any], right_meta) if isinstance(right_meta, dict) else None
                )
                left_marker = (
                    left_meta_dict.get(RUNTIME_CONTEXT_MESSAGE_META)
                    if left_meta_dict is not None
                    else None
                )
                right_marker = (
                    right_meta_dict.get(RUNTIME_CONTEXT_MESSAGE_META)
                    if right_meta_dict is not None
                    else None
                )
                left_marker_dict = (
                    cast(dict[str, Any], left_marker) if isinstance(left_marker, dict) else None
                )
                right_marker_dict = (
                    cast(dict[str, Any], right_marker) if isinstance(right_marker, dict) else None
                )
                empty_sources: list[str] = []
                empty_blocks: list[dict[str, Any]] = []
                detached_left = (
                    detach_runtime_context(merged.get("content"), left_marker_dict)
                    if left_marker_dict is not None
                    else (merged.get("content"), empty_sources, empty_blocks)
                )
                detached_right = (
                    detach_runtime_context(injection.get("content"), right_marker_dict)
                    if right_marker_dict is not None
                    else (injection.get("content"), empty_sources, empty_blocks)
                )
                if detached_left is not None and detached_right is not None:
                    left_content, left_sources, left_blocks = detached_left
                    right_content, right_sources, right_blocks = detached_right
                    merged_content = cls._merge_message_content(left_content, right_content)
                    context_blocks = [*left_blocks, *right_blocks]
                    if context_blocks:
                        merged_content, marker = reattach_runtime_context(
                            merged_content,
                            [*left_sources, *right_sources],
                            context_blocks,
                        )
                        internal_meta = (
                            dict(left_meta_dict) if left_meta_dict is not None else {}
                        )
                        if right_meta_dict is not None:
                            for key, value in right_meta_dict.items():
                                internal_meta.setdefault(key, value)
                        internal_meta[RUNTIME_CONTEXT_MESSAGE_META] = marker
                        merged["_meta"] = internal_meta
                    merged["content"] = merged_content
                else:
                    merged["content"] = cls._merge_message_content(
                        merged.get("content"),
                        injection.get("content"),
                    )
                prepared[-1] = merged
                continue
            prepared.append(injection)
        return prepared

    def prepare_messages_for_model(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Build the normalized model-facing copy of a raw transcript."""
        governed = self.prepare_for_model(config, messages)
        return self._merge_adjacent_user_messages_for_model(governed)

    def prepare_for_model(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        updated = self.strip_placeholder_assistant_messages(messages)
        updated = self.strip_malformed_tool_calls(updated)
        updated = self.drop_orphan_tool_results(updated)
        updated = self.backfill_missing_tool_results(updated)
        return self.apply_tool_result_budget(config, updated)

    def fit_to_budget(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
        *,
        tool_definitions: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Fit a model-facing copy while keeping the source transcript intact."""
        updated = self.snip_history(
            config,
            messages,
            tool_definitions=tool_definitions,
            force=True,
        )
        updated = self.drop_orphan_tool_results(updated)
        updated = self.backfill_missing_tool_results(updated)
        return self.ensure_request_fits(
            config,
            updated,
            tool_definitions=tool_definitions,
        )

    def ensure_request_fits(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
        *,
        tool_definitions: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Validate an exact model request without dropping any messages."""
        if not config.context_window_tokens:
            return messages
        budget = self.input_budget(config)
        estimated, source = estimate_prompt_tokens_chain(
            config.provider,
            config.model,
            messages,
            tool_definitions,
        )
        if budget > 0 and estimated <= budget:
            return messages
        raise ContextWindowExceededError(
            session_key=config.session_key,
            estimated_tokens=estimated,
            input_budget=budget,
            source=source,
        )

    def request_pressure(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
        usage: LLMUsage | None,
        *,
        usage_matches_messages: bool,
        tool_definitions: list[dict[str, Any]] | None,
        request_context_tokens: int | None = None,
    ) -> tuple[int, str] | None:
        """Return the authoritative measurement when a request is pressured."""
        if not config.context_window_tokens:
            return None
        budget = self.input_budget(config)
        if request_context_tokens is not None:
            measured = request_context_tokens
            source = "resumed provider state plus pending messages"
        elif (
            usage_matches_messages
            and usage is not None
            and usage.context_tokens is not None
        ):
            measured = usage.context_tokens
            source = "matching provider usage"
        else:
            measured, source = estimate_prompt_tokens_chain(
                config.provider,
                config.model,
                messages,
                tool_definitions,
            )
        if budget > 0 and measured < budget:
            return None
        return measured, source

    @staticmethod
    def _summary_transcript(
        compaction: ContextCompactionState,
        summary: str,
    ) -> list[dict[str, Any]]:
        """Rebuild only the stable system prefix around a replacement summary."""
        return compaction.transcript_builder(
            replace(
                compaction.transcript_input,
                history=[],
                current_message=None,
                media=None,
                session_summary={
                    "text": summary,
                    "last_active": datetime.now().astimezone().isoformat(),
                },
                runtime_context_blocks=None,
            )
        )

    async def summarize_provider_compaction(
        self,
        state: ModelRequestState,
        response: LLMResponse,
        *,
        current_request_boundary: int | None,
    ) -> None:
        """Materialize the exact input replaced by provider-native compaction."""
        compaction = state.compaction
        if (
            not response.provider_compaction_applied
            or response.provider_compaction_state is None
            or compaction is None
            or compaction.consolidate_provider_compaction is None
        ):
            return

        if response.provider_compaction_scope == "prior_context":
            accepted_messages = compaction.accepted_messages
            transcript_boundary = compaction.raw_accepted_boundary
        elif (
            response.provider_compaction_scope == "current_request"
            and state.messages is not None
            and current_request_boundary is not None
        ):
            accepted_messages = state.messages
            transcript_boundary = current_request_boundary
        else:
            logger.warning(
                "Ignoring provider compaction with missing request-boundary scope for {}",
                state.config.session_key or "default",
            )
            return

        compaction_id = uuid4().hex
        await emit_context_compaction(
            state.compaction_callback,
            ContextCompactionEvent(compaction_id=compaction_id, phase="started"),
        )
        try:
            summary = await compaction.consolidate_provider_compaction(
                response.provider_compaction_state,
                deepcopy(accepted_messages),
                compaction.active_summary,
            )
        except (Exception, asyncio.CancelledError) as exc:
            await emit_context_compaction(
                state.compaction_callback,
                ContextCompactionEvent(
                    compaction_id=compaction_id,
                    phase="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                ),
            )
            raise
        if not summary:
            await emit_context_compaction(
                state.compaction_callback,
                ContextCompactionEvent(compaction_id=compaction_id, phase="failed"),
            )
            return
        compaction.active_summary = summary
        compaction.summary_checkpoint = SessionSummaryCheckpoint(
            summary=summary,
            transcript_boundary=transcript_boundary,
        )
        await emit_context_compaction(
            state.compaction_callback,
            ContextCompactionEvent(
                compaction_id=compaction_id,
                phase="succeeded",
            ),
        )

    async def _compact_request_history(
        self,
        state: ModelRequestState,
        compaction: ContextCompactionState,
        messages: list[dict[str, Any]],
        pressure: tuple[int, str],
        *,
        tool_definitions: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """Replace accepted history H with a checkpoint while preserving delta."""
        measured, _source = pressure
        compaction_id = uuid4().hex
        await emit_context_compaction(
            state.compaction_callback,
            ContextCompactionEvent(compaction_id=compaction_id, phase="started"),
        )
        try:
            delta_messages = compaction.delta_after_accepted(messages)
            consolidation_prefix = self.prepare_messages_for_model(
                state.config,
                compaction.accepted_messages,
            )
            summary = await compaction.consolidate_history(
                deepcopy(consolidation_prefix),
                compaction.active_summary,
            )
            if not summary:
                raise ContextWindowExceededError(
                    session_key=state.config.session_key,
                    estimated_tokens=measured,
                    input_budget=self.input_budget(state.config),
                    source=_source,
                )

            compaction.active_summary = summary
            prepared = self.prepare_messages_for_model(
                state.config,
                [
                    *self._summary_transcript(compaction, summary),
                    {"role": "user", "content": SUMMARY_CONTINUATION_TEXT},
                    *delta_messages,
                ],
            )
            # Responses-style state is append-only. Replacing H with a
            # checkpoint requires a fresh request; a successful response may
            # establish a new provider-owned state at the rewritten boundary.
            state.conversation.replace_transcript(compaction.raw_messages)
            state.usage = None
            prepared = self.ensure_request_fits(
                state.config,
                prepared,
                tool_definitions=tool_definitions,
            )
            compaction.summary_checkpoint = SessionSummaryCheckpoint(
                summary=summary,
                transcript_boundary=compaction.raw_accepted_boundary,
            )
        except (Exception, asyncio.CancelledError) as exc:
            await emit_context_compaction(
                state.compaction_callback,
                ContextCompactionEvent(
                    compaction_id=compaction_id,
                    phase="cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                ),
            )
            raise
        await emit_context_compaction(
            state.compaction_callback,
            ContextCompactionEvent(
                compaction_id=compaction_id,
                phase="succeeded",
            ),
        )
        return prepared

    async def prepare_request(
        self,
        state: ModelRequestState,
        messages: list[dict[str, Any]],
        *,
        tool_definitions: list[dict[str, Any]] | None,
        transcript: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], ProviderCallContext | None]:
        """Prepare, compact or fit, and record the exact provider payload."""
        prepared = self.prepare_messages_for_model(state.config, messages)
        model_messages: list[dict[str, Any]] | None = prepared
        supplemental_messages: list[dict[str, Any]] | None = None
        request_context_tokens = None
        if transcript is not None:
            if tool_definitions is None:
                model_messages = None
                supplemental_messages = [prepared[-1]]
            request_context_tokens = state.conversation.estimate_request_context_tokens(
                transcript,
                model_messages=model_messages,
                supplemental_messages=supplemental_messages,
                tool_definitions=tool_definitions,
            )
        usage_matches_messages = (
            state.messages is not None
            and prepared == state.messages
            and tool_definitions == state.tool_definitions
        )
        request_was_fitted = False
        compaction = state.compaction
        if compaction is None:
            pressure = self.request_pressure(
                state.config,
                prepared,
                state.usage,
                usage_matches_messages=usage_matches_messages,
                tool_definitions=tool_definitions,
                request_context_tokens=request_context_tokens,
            )
            if pressure is not None:
                compaction_id = uuid4().hex
                await emit_context_compaction(
                    state.compaction_callback,
                    ContextCompactionEvent(compaction_id=compaction_id, phase="started"),
                )
                try:
                    prepared = self.fit_to_budget(
                        state.config,
                        prepared,
                        tool_definitions=tool_definitions,
                    )
                except Exception:
                    await emit_context_compaction(
                        state.compaction_callback,
                        ContextCompactionEvent(compaction_id=compaction_id, phase="failed"),
                    )
                    raise
                await emit_context_compaction(
                    state.compaction_callback,
                    ContextCompactionEvent(compaction_id=compaction_id, phase="succeeded"),
                )
                request_was_fitted = True
        else:
            pressure = self.request_pressure(
                state.config,
                prepared,
                state.usage,
                usage_matches_messages=usage_matches_messages,
                tool_definitions=tool_definitions,
                request_context_tokens=request_context_tokens,
            )
            if pressure is not None:
                prepared = await self._compact_request_history(
                    state,
                    compaction,
                    messages,
                    pressure,
                    tool_definitions=tool_definitions,
                )
                model_messages = prepared
                supplemental_messages = None
        provider_context = (
            state.conversation.prepare_request(
                transcript,
                context_window_tokens=state.config.context_window_tokens,
                model_messages=model_messages,
                supplemental_messages=supplemental_messages,
                resume_state=not request_was_fitted,
            )
            if transcript is not None
            else state.conversation.independent_request_context(
                context_window_tokens=state.config.context_window_tokens,
            )
        )
        state.messages = deepcopy(prepared)
        state.tool_definitions = deepcopy(tool_definitions)
        return prepared, provider_context

    @staticmethod
    def input_budget(config: ContextGovernanceConfig) -> int:
        if not config.context_window_tokens:
            return 0

        provider_max_tokens = getattr(
            getattr(config.provider, "generation", None),
            "max_tokens",
            4096,
        )
        max_output = config.max_tokens if isinstance(config.max_tokens, int) else (
            provider_max_tokens if isinstance(provider_max_tokens, int) else 4096
        )
        budget = config.context_block_limit or (
            config.context_window_tokens - max_output - SNIP_SAFETY_BUFFER
        )
        return budget if budget > 0 else 0

    @staticmethod
    def normalize_tool_result(
        config: ContextGovernanceConfig,
        tool_call_id: str,
        tool_name: str,
        result: Any,
    ) -> Any:
        result = ensure_nonempty_tool_result(tool_name, result)
        if tool_name in TOOL_RESULT_OFFLOAD_EXEMPT_TOOLS:
            return result
        try:
            content = maybe_persist_tool_result(
                config.workspace,
                config.session_key,
                tool_call_id,
                result,
                max_chars=config.max_tool_result_chars,
            )
        except Exception:
            logger.exception(
                "Tool result persist failed for {} in {}; using raw result",
                tool_call_id,
                config.session_key or "default",
            )
            content = result
        if isinstance(content, str) and len(content) > config.max_tool_result_chars:
            return truncate_text(content, config.max_tool_result_chars)
        return content

    @staticmethod
    def strip_placeholder_assistant_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Remove assistant messages that are compaction placeholders.

        Messages like ``[Previous assistant message omitted.]`` carry no useful
        context for the model and can cause it to repeatedly attempt tool calls
        that previously failed, producing malformed responses in a loop.
        Consecutive same-role messages that result from removal are handled
        downstream by the provider's merge-consecutive logic. Only the
        model-facing copy is repaired; the persisted transcript is untouched
        (a copy is returned, or the same list object when nothing changes).
        """
        updated: list[dict[str, Any]] | None = None
        for idx, msg in enumerate(messages):
            if msg.get("role") != "assistant":
                if updated is not None:
                    updated.append(msg)
                continue
            content = msg.get("content", "")
            text = content if isinstance(content, str) else ""
            is_placeholder = text.strip() in PLACEHOLDER_TEXTS
            has_tool_calls = bool(msg.get("tool_calls"))
            if is_placeholder and not has_tool_calls:
                if updated is None:
                    updated = list(messages[:idx])
                logger.debug(
                    "Stripping placeholder assistant message from history: {!r}",
                    text[:60],
                )
                continue
            if updated is not None:
                updated.append(msg)
        if updated is None:
            return messages
        return updated

    @staticmethod
    def strip_malformed_tool_calls(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drop persisted assistant tool_calls whose name is missing/non-string.

        A degenerate tool call (``name=None`` or ``""``) that slipped into the
        saved history before this guard existed gets replayed on every turn and
        makes upstream APIs reject the whole request
        (``messages.content.N.tool_use.name: Input should be a valid string``),
        permanently wedging the session. Removing the bad call here lets the
        existing orphan-result cleanup drop its now-dangling tool result, so a
        polluted session self-heals on its next turn. The persisted transcript
        is left untouched; only the model-facing copy is repaired (a copy is
        returned, or the same list object when nothing changes).
        """
        updated: list[dict[str, Any]] | None = None
        for idx, msg in enumerate(messages):
            if msg.get("role") != "assistant":
                if updated is not None:
                    updated.append(msg)
                continue
            calls = msg.get("tool_calls")
            if not calls:
                if updated is not None:
                    updated.append(msg)
                continue
            kept = [tc for tc in cast(list[Any], calls) if _tool_call_name_is_valid(tc)]
            if len(kept) == len(calls):
                if updated is not None:
                    updated.append(msg)
                continue
            if updated is None:
                updated = [dict(m) for m in messages[:idx]]
            logger.warning(
                "Stripping {} malformed tool_call(s) with missing/non-string "
                "name from assistant history before request",
                len(calls) - len(kept),
            )
            repaired = dict(msg)
            if kept:
                repaired["tool_calls"] = kept
            else:
                repaired.pop("tool_calls", None)
            # An assistant turn with neither content nor any valid tool call is
            # itself invalid upstream; drop it entirely in that case.
            has_content = bool(repaired.get("content"))
            if not kept and not has_content:
                continue
            updated.append(repaired)

        if updated is None:
            return messages
        return updated

    @staticmethod
    def drop_orphan_tool_results(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drop invalid tool results before history is sent back to providers."""
        declared: set[str] = set()
        fulfilled: set[str] = set()
        updated: list[dict[str, Any]] | None = None
        for idx, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant":
                for tc in cast(list[Any], msg.get("tool_calls") or []):
                    if isinstance(tc, dict):
                        tool_call = cast(dict[str, Any], tc)
                        if tool_call.get("id"):
                            declared.add(str(tool_call["id"]))
            if role == "tool":
                tid = msg.get("tool_call_id")
                tid_str = str(tid) if tid else ""
                if not tid_str or tid_str not in declared or tid_str in fulfilled:
                    if updated is None:
                        updated = [dict(m) for m in messages[:idx]]
                    continue
                fulfilled.add(tid_str)
            if updated is not None:
                updated.append(dict(msg))

        if updated is None:
            return messages
        return updated

    @staticmethod
    def backfill_missing_tool_results(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Insert synthetic error results for assistant tool_calls with missing tool outputs."""
        declared: list[tuple[int, str, str]] = []
        fulfilled: set[str] = set()
        for idx, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant":
                for tc in cast(list[Any], msg.get("tool_calls") or []):
                    if isinstance(tc, dict):
                        name = ""
                        tool_call = cast(dict[str, Any], tc)
                        if tool_call.get("id"):
                            func = tool_call.get("function")
                            if isinstance(func, dict):
                                func_data = cast(dict[str, Any], func)
                                raw_name = func_data.get("name", "")
                                name = raw_name if isinstance(raw_name, str) else str(raw_name)
                            declared.append((idx, str(tool_call["id"]), name))
            elif role == "tool":
                tid = msg.get("tool_call_id")
                if tid:
                    fulfilled.add(str(tid))

        missing = [(ai, cid, name) for ai, cid, name in declared if cid not in fulfilled]
        if not missing:
            return messages

        updated = list(messages)
        offset = 0
        for assistant_idx, call_id, name in missing:
            insert_at = assistant_idx + 1 + offset
            while insert_at < len(updated) and updated[insert_at].get("role") == "tool":
                insert_at += 1
            updated.insert(insert_at, {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": BACKFILL_CONTENT,
            })
            offset += 1
        return updated

    def apply_tool_result_budget(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        updated = messages
        for idx, message in enumerate(messages):
            if message.get("role") != "tool":
                continue
            normalized = self.normalize_tool_result(
                config,
                str(message.get("tool_call_id") or f"tool_{idx}"),
                str(message.get("name") or "tool"),
                message.get("content"),
            )
            if normalized != message.get("content"):
                if updated is messages:
                    updated = [dict(m) for m in messages]
                updated[idx]["content"] = normalized
        return updated

    def snip_history(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
        *,
        tool_definitions: list[dict[str, Any]] | None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        if not messages or not config.context_window_tokens:
            return messages

        budget = self.input_budget(config)
        if budget <= 0:
            return messages

        if not force:
            estimate, _ = estimate_prompt_tokens_chain(
                config.provider,
                config.model,
                messages,
                tool_definitions,
            )
            if estimate <= budget:
                return messages

        system_messages = [dict(msg) for msg in messages if msg.get("role") == "system"]
        non_system = [dict(msg) for msg in messages if msg.get("role") != "system"]
        if not non_system:
            return messages

        system_tokens = sum(estimate_message_tokens(msg) for msg in system_messages)
        fixed_tokens, _ = estimate_prompt_tokens_chain(
            config.provider,
            config.model,
            system_messages,
            tool_definitions,
        )
        remaining_budget = max(0, budget - max(system_tokens, fixed_tokens))
        kept: list[dict[str, Any]] = []
        kept_tokens = 0
        for message in reversed(non_system):
            msg_tokens = estimate_message_tokens(message)
            if kept and kept_tokens + msg_tokens > remaining_budget:
                break
            kept.append(message)
            kept_tokens += msg_tokens
        kept.reverse()

        return system_messages + self._legal_history_tail(kept, non_system)

    def _legal_history_tail(
        self,
        kept: list[dict[str, Any]],
        non_system: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fallback = kept if kept else (non_system[-1:] if non_system else [])
        kept = self._user_tail(kept) or self._user_tail(non_system, last=True) or fallback

        start = find_legal_message_start(kept)
        return kept[start:] if start else kept

    @staticmethod
    def _user_tail(messages: list[dict[str, Any]], *, last: bool = False) -> list[dict[str, Any]]:
        indexes = range(len(messages) - 1, -1, -1) if last else range(len(messages))
        for idx in indexes:
            if messages[idx].get("role") == "user":
                return messages[idx:]
        return []
