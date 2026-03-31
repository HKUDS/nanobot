"""Shared helpers for OpenAI Responses API providers (Codex, Azure OpenAI)."""

from nanobot.providers.openai_responses_common.converters import (
    convert_messages,
    convert_tools,
    convert_user_message,
    split_tool_call_id,
)
from nanobot.providers.openai_responses_common.parsing import (
    FINISH_REASON_MAP,
    consume_sdk_stream,
    consume_sse,
    iter_sse,
    map_finish_reason,
    parse_response_output,
)

__all__ = [
    "convert_messages",
    "convert_tools",
    "convert_user_message",
    "split_tool_call_id",
    "iter_sse",
    "consume_sse",
    "consume_sdk_stream",
    "map_finish_reason",
    "parse_response_output",
    "FINISH_REASON_MAP",
]
