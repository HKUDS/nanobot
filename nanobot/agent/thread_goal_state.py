"""``Session.metadata`` thread goal: shared key, parse, runtime-context lines.

Tools write this blob; ``ContextBuilder`` reads via ``runtime_lines_for_metadata``
without importing tool modules.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

THREAD_GOAL_KEY = "thread_goal"
_MAX_OBJECTIVE_IN_RUNTIME = 4000


def parse_thread_goal(blob: Any) -> dict[str, Any] | None:
    if blob is None:
        return None
    if isinstance(blob, dict):
        return blob
    if isinstance(blob, str):
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def runtime_lines_for_metadata(metadata: Mapping[str, Any] | None) -> list[str]:
    """Lines appended inside the Runtime Context block when a goal is active."""
    if not metadata:
        return []
    goal = parse_thread_goal(metadata.get(THREAD_GOAL_KEY))
    if not isinstance(goal, dict) or goal.get("status") != "active":
        return []
    objective = str(goal.get("objective") or "").strip()
    if not objective:
        return ["Thread goal: active (no objective text stored)."]
    if len(objective) > _MAX_OBJECTIVE_IN_RUNTIME:
        objective = objective[:_MAX_OBJECTIVE_IN_RUNTIME].rstrip() + "\n… (truncated)"
    out = ["Thread goal (active):", objective]
    hint = str(goal.get("ui_summary") or "").strip()
    if hint:
        out.append(f"Summary: {hint}")
    return out
