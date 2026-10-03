"""Shared helpers for provider backends that implement the OpenAI Responses protocol."""

from nanobot.providers.openai_responses.converters import (
    convert_messages,
    convert_tools,
    convert_user_message,
    split_tool_call_id,
)
from nanobot.providers.openai_responses.parsing import (
    FINISH_REASON_MAP,
    ResponsesStreamCapture,
    consume_sdk_stream,
    consume_sse,
    consume_sse_with_reasoning,
    is_replayable_finish_reason,
    iter_sse,
    map_finish_reason,
    parse_response_output,
)
from nanobot.providers.openai_responses.state import (
    build_responses_compaction_state,
    build_responses_state,
    is_compaction_compatibility_error,
    prepare_responses_input,
    resolve_compact_threshold,
    responses_state_context_tokens,
    responses_state_items,
    responses_state_matches,
)

__all__ = [
    "convert_messages",
    "convert_tools",
    "convert_user_message",
    "split_tool_call_id",
    "iter_sse",
    "consume_sse",
    "consume_sse_with_reasoning",
    "consume_sdk_stream",
    "ResponsesStreamCapture",
    "is_replayable_finish_reason",
    "map_finish_reason",
    "parse_response_output",
    "build_responses_compaction_state",
    "build_responses_state",
    "is_compaction_compatibility_error",
    "prepare_responses_input",
    "resolve_compact_threshold",
    "responses_state_context_tokens",
    "responses_state_items",
    "responses_state_matches",
    "FINISH_REASON_MAP",
]
