"""Helpers for provider-safe tool call identifiers."""

from __future__ import annotations

import hashlib

MAX_TOOL_CALL_ID_LENGTH = 64


def shorten_overlong_tool_call_id(tool_call_id: str) -> str:
    if len(tool_call_id) <= MAX_TOOL_CALL_ID_LENGTH:
        return tool_call_id
    return "call_" + hashlib.sha1(tool_call_id.encode()).hexdigest()
