"""Helpers for provider-safe tool call identifiers."""

from __future__ import annotations

import hashlib

OPENAI_CHAT_TOOL_CALL_ID_MAX_LENGTH = 40
OPENAI_RESPONSES_TOOL_CALL_ID_MAX_LENGTH = 64


def shorten_overlong_tool_call_id(
    tool_call_id: str,
    *,
    max_length: int = OPENAI_RESPONSES_TOOL_CALL_ID_MAX_LENGTH,
) -> str:
    if len(tool_call_id) <= max_length:
        return tool_call_id
    digest_length = max(0, max_length - len("call_"))
    return "call_" + hashlib.sha1(tool_call_id.encode()).hexdigest()[:digest_length]
