"""Input boundaries for Responses trigger compaction."""

from __future__ import annotations

import json
from typing import Any

_COMPACTION_RETAINED_CHAR_BUDGET = 256_000


def split_compaction_input(
    history_items: list[dict[str, Any]],
    delta_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep pending outputs and their function calls after the compaction boundary."""
    pending_ids = {
        item["call_id"] for item in delta_items
        if item.get("type") == "function_call_output" and isinstance(item.get("call_id"), str)
    }
    history: list[dict[str, Any]] = []
    pending_calls: list[dict[str, Any]] = []
    for item in history_items:
        if item.get("type") == "function_call" and item.get("call_id") in pending_ids:
            pending_calls.append(item)
        else:
            history.append(item)
    # Compaction rejects unanswered calls; the following generation request
    # needs each original call before its still-unsubmitted output.
    return history, [*pending_calls, *delta_items]


def retained_compaction_messages(
    input_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Retain bounded user/developer/system messages across trigger compaction."""
    retained_reversed: list[dict[str, Any]] = []
    remaining = _COMPACTION_RETAINED_CHAR_BUDGET
    for item in reversed(input_items):
        if item.get("type") not in {None, "message"} or item.get("role") not in {
            "user",
            "developer",
            "system",
        }:
            continue
        size = len(json.dumps(item, ensure_ascii=False))
        if size > remaining and retained_reversed:
            continue
        retained_reversed.append(item)
        remaining = max(0, remaining - size)
        if remaining == 0:
            break
    retained_reversed.reverse()
    return retained_reversed
