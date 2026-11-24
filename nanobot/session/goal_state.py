"""Session metadata helpers for explicit sustained goals."""

from __future__ import annotations

from typing import Any, Mapping, cast

GOAL_STATE_KEY = "goal_state"
GOAL_COMMAND = "/goal"
MAX_GOAL_OBJECTIVE_CHARS = 4000


def read_goal_state(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    goal = metadata.get(GOAL_STATE_KEY) if metadata is not None else None
    return cast(dict[str, Any], goal) if isinstance(goal, dict) else None


def sustained_goal_active(metadata: Mapping[str, Any] | None) -> bool:
    """True when this session has an active sustained objective."""
    goal = read_goal_state(metadata)
    return goal is not None and goal.get("status") == "active"


def explicit_goal_requested(message_metadata: Mapping[str, Any] | None) -> bool:
    """True when this turn was explicitly started by the ``/goal`` command."""
    if not message_metadata:
        return False
    if message_metadata.get("goal_requested") is True:
        return True
    return str(message_metadata.get("original_command") or "").strip() == GOAL_COMMAND


def goal_state_runtime_lines(metadata: Mapping[str, Any] | None) -> list[str]:
    """Lines appended inside the Runtime Context block for active or blocked goals."""
    goal = read_goal_state(metadata)
    if goal is None or goal.get("status") not in {"active", "blocked"}:
        return []
    status = goal["status"]
    objective = str(goal.get("objective") or "").strip()
    if not objective:
        return [f"Goal: {status} (no objective text stored)."]
    if len(objective) > MAX_GOAL_OBJECTIVE_CHARS:
        objective = objective[:MAX_GOAL_OBJECTIVE_CHARS].rstrip() + "\n… (truncated)"
    out = [f"Goal ({status}):", objective]
    hint = str(goal.get("ui_summary") or "").strip()
    if hint:
        out.append(f"Summary: {hint}")
    return out
