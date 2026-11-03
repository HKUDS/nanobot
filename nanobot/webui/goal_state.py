"""WebUI projection of persisted sustained-goal state."""

from __future__ import annotations

from typing import Any, Mapping

from nanobot.session.goal_state import goal_state_raw, parse_goal_state

_MAX_OBJECTIVE_WS = 600


def goal_state_ws_blob(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """JSON-safe snapshot for WebSocket ``goal_state`` events (one chat_id per frame)."""
    goal = parse_goal_state(goal_state_raw(metadata))
    if isinstance(goal, dict) and goal.get("status") in {"active", "blocked"}:
        status = str(goal.get("status"))
        objective = str(goal.get("objective") or "").strip()
        if len(objective) > _MAX_OBJECTIVE_WS:
            objective = objective[:_MAX_OBJECTIVE_WS].rstrip() + "…"
        summary = str(goal.get("ui_summary") or "").strip()[:120]
        blob: dict[str, Any] = {"active": status == "active", "status": status}
        if summary:
            blob["ui_summary"] = summary
        if objective:
            blob["objective"] = objective
        recap = str(goal.get("recap") or "").strip()[:240]
        if recap:
            blob["recap"] = recap
        return blob
    return {"active": False}
