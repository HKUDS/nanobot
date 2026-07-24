"""Minimal command tools for the durable Goal state graph."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import current_request_context
from nanobot.goals import (
    Goal,
    GoalConflictError,
    GoalError,
    GoalStore,
    compact_ref,
    projection,
    workspace_fingerprint,
)
from nanobot.session.goal_state import GOAL_STATE_KEY, parse_goal_state

GOAL_NODE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 64},
        "title": {"type": "string", "minLength": 1, "maxLength": 300},
        "outcome": {"type": "string", "minLength": 1, "maxLength": 2000},
        "kind": {"type": "string", "enum": ["action", "coarse"]},
        "depends_on": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 64},
            "maxItems": 32,
        },
    },
    "required": ["id", "title", "outcome", "depends_on"],
    "additionalProperties": False,
}


class _GoalPlanTool(Tool):
    def __init__(
        self,
        sessions: Any,
        *,
        workspace: str | Path | None = None,
        goal_store_root: str | Path | None = None,
    ) -> None:
        self.sessions = sessions
        self.workspace = Path(workspace or sessions.workspace).expanduser().resolve(strict=False)
        self.goal_store_root = Path(goal_store_root) if goal_store_root is not None else None

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        sessions = getattr(ctx, "sessions", None)
        assert sessions is not None
        return cls(sessions, workspace=getattr(ctx, "workspace", None))

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "sessions", None) is not None

    def _workspace(self) -> Path:
        request = current_request_context()
        if request is not None and request.workspace is not None:
            return Path(request.workspace).expanduser().resolve(strict=False)
        return self.workspace

    def _load(self) -> tuple[Any, dict[str, Any], GoalStore, Goal] | None:
        request = current_request_context()
        if request is None or not request.session_key:
            return None
        session = self.sessions.get_or_create(request.session_key)
        ref = parse_goal_state(session.metadata.get(GOAL_STATE_KEY))
        if not isinstance(ref, dict) or ref.get("status") != "active":
            return None
        workspace = self._workspace()
        if ref.get("workspace") != workspace_fingerprint(workspace):
            raise GoalError("Goal reference belongs to a different workspace")
        store = GoalStore.for_workspace(workspace, root=self.goal_store_root)
        goal = store.get(str(ref.get("goal_id") or ""))
        if goal is None or goal.status != "active":
            raise GoalError("active Goal reference could not be resolved")
        return session, ref, store, goal

    def _save(self, session: Any, goal: Goal) -> None:
        previous = deepcopy(session.metadata)
        session.metadata[GOAL_STATE_KEY] = compact_ref(goal, self._workspace())
        try:
            self.sessions.save(session)
        except BaseException:
            session.metadata.clear()
            session.metadata.update(previous)
            raise

    @staticmethod
    def _result(goal: Goal) -> str:
        return json.dumps(projection(goal), ensure_ascii=False)


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "expected_version": {"type": "integer", "minimum": 1},
            "nodes": {
                "type": "array",
                "items": GOAL_NODE_SCHEMA,
                "minItems": 1,
                "maxItems": 64,
            },
        },
        "required": ["expected_version", "nodes"],
        "additionalProperties": False,
    }
)
class PlanGoalTool(_GoalPlanTool):
    @property
    def name(self) -> str:
        return "plan_goal"

    @property
    def description(self) -> str:
        return (
            "Create the active Goal's initial dependency graph. Split the objective into stable "
            "outcome nodes; dependencies must form a DAG. Mark work that needs later refinement "
            "as kind='coarse' instead of guessing its executable steps."
        )

    async def execute(self, expected_version: int, nodes: list[dict[str, Any]], **kwargs: Any) -> str:
        try:
            loaded = self._load()
            if loaded is None:
                return ToolResult.error("Error: plan_goal requires an active durable Goal.")
            session, _ref, store, goal = loaded
            updated = await asyncio.to_thread(
                store.apply,
                goal.id,
                expected_version,
                {"action": "plan", "nodes": nodes},
            )
            self._save(session, updated)
            return self._result(updated)
        except (GoalConflictError, GoalError, TypeError, ValueError) as exc:
            return ToolResult.error(f"Error: Goal plan was rejected: {exc}")


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "expected_version": {"type": "integer", "minimum": 1},
            "node_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "nodes": {
                "type": "array",
                "items": GOAL_NODE_SCHEMA,
                "minItems": 1,
                "maxItems": 16,
            },
        },
        "required": ["expected_version", "node_id", "nodes"],
        "additionalProperties": False,
    }
)
class ExpandGoalNodeTool(_GoalPlanTool):
    @property
    def name(self) -> str:
        return "expand_goal_node"

    @property
    def description(self) -> str:
        return (
            "Refine one expandable coarse node into a child DAG when its dependencies have "
            "succeeded. This is normal rolling-wave planning, not failure recovery, and does not "
            "set needs_replan."
        )

    async def execute(
        self,
        expected_version: int,
        node_id: str,
        nodes: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        try:
            loaded = self._load()
            if loaded is None:
                return ToolResult.error("Error: expand_goal_node requires an active durable Goal.")
            session, _ref, store, goal = loaded
            updated = await asyncio.to_thread(
                store.apply,
                goal.id,
                expected_version,
                {"action": "expand", "node_id": node_id, "nodes": nodes},
            )
            self._save(session, updated)
            return self._result(updated)
        except (GoalConflictError, GoalError, TypeError, ValueError) as exc:
            return ToolResult.error(f"Error: Goal expansion was rejected: {exc}")


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "expected_version": {"type": "integer", "minimum": 1},
            "node_id": {"type": "string", "minLength": 1, "maxLength": 64},
            "action": {"type": "string", "enum": ["begin", "succeed", "block"]},
            "result": {"type": ["string", "null"], "maxLength": 8000},
            "reason": {"type": ["string", "null"], "maxLength": 8000},
        },
        "required": ["expected_version", "node_id", "action"],
        "additionalProperties": False,
    }
)
class UpdateGoalNodeTool(_GoalPlanTool):
    @property
    def name(self) -> str:
        return "update_goal_node"

    @property
    def description(self) -> str:
        return (
            "Apply one constrained node transition: begin a ready node, succeed a running node "
            "with a result summary, or block a ready/running node with failure evidence. Blocking "
            "one path never terminates the Goal or prevents independent ready work."
        )

    async def execute(
        self,
        expected_version: int,
        node_id: str,
        action: str,
        result: str | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            loaded = self._load()
            if loaded is None:
                return ToolResult.error("Error: update_goal_node requires an active durable Goal.")
            session, _ref, store, goal = loaded
            command = {
                "action": action,
                "node_id": node_id,
                "result": result,
                "reason": reason,
            }
            updated = await asyncio.to_thread(store.apply, goal.id, expected_version, command)
            self._save(session, updated)
            return self._result(updated)
        except (GoalConflictError, GoalError, TypeError, ValueError) as exc:
            return ToolResult.error(f"Error: Goal node update was rejected: {exc}")


@tool_parameters({"type": "object", "properties": {}, "additionalProperties": False})
class GetGoalPlanTool(_GoalPlanTool):
    @property
    def name(self) -> str:
        return "get_goal_plan"

    @property
    def description(self) -> str:
        return "Read the authoritative bounded Goal graph projection and current version."

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        try:
            loaded = self._load()
            if loaded is None:
                return ToolResult.error("Error: get_goal_plan requires an active durable Goal.")
            return self._result(loaded[3])
        except (GoalError, ValueError) as exc:
            return ToolResult.error(f"Error: Goal plan could not be read: {exc}")
