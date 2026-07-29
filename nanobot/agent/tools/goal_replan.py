"""Clean-context recovery planning for one blocked Goal path."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping

from nanobot.agent.tools.base import Schema, ToolResult, tool_parameters
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.goal_plan import GOAL_NODE_SCHEMA, _GoalPlanTool
from nanobot.goals import Goal, GoalConflictError, GoalError
from nanobot.providers.base import parse_tool_arguments

_MAX_RECOVERY_NODES = 16
_SUBMIT_PARAMETERS = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
        "nodes": {
            "type": "array",
            "items": GOAL_NODE_SCHEMA,
            "minItems": 1,
            "maxItems": _MAX_RECOVERY_NODES,
        },
    },
    "required": ["rationale", "nodes"],
    "additionalProperties": False,
}
_SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_recovery_plan",
        "description": "Submit the smallest valid replacement DAG for the blocked path.",
        "parameters": _SUBMIT_PARAMETERS,
    },
}
_SYSTEM_PROMPT = """You are a Recovery Planner operating in a clean context.
You receive only durable Goal evidence, never the original chat. Repair the specified blocked path;
do not expand unrelated scope or declare the Goal terminated. Avoid repeating recorded failures.
Return the smallest replacement DAG through submit_recovery_plan. Node IDs must be new. Dependencies
may reference only new nodes or the listed succeeded node IDs. The replacement DAG leaves will be
connected automatically to the blocked node's downstream consumers."""


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "expected_version": {"type": "integer", "minimum": 1},
            "blocked_node_id": {"type": "string", "minLength": 1, "maxLength": 64},
        },
        "required": ["expected_version", "blocked_node_id"],
        "additionalProperties": False,
    }
)
class ReplanGoalTool(_GoalPlanTool):
    @property
    def name(self) -> str:
        return "replan_goal"

    @property
    def description(self) -> str:
        return (
            "Repair one blocked Goal path with a clean-context Recovery Planner. It receives the "
            "ultimate objective, successful predecessor results, bounded progress, and failure "
            "experience, then atomically replaces only that path. Independent work stays active."
        )

    async def execute(
        self,
        expected_version: int,
        blocked_node_id: str,
        **kwargs: Any,
    ) -> str:
        try:
            loaded = self._load()
            if loaded is None:
                return ToolResult.error("Error: replan_goal requires an active durable Goal.")
            session, _ref, store, goal = loaded
            if goal.version != expected_version:
                raise GoalConflictError(
                    f"goal is at version {goal.version}, expected {expected_version}"
                )
            target = goal.state.get("nodes", {}).get(blocked_node_id)
            if not isinstance(target, dict) or target.get("status") != "blocked":
                raise GoalError("Recovery Planner requires a blocked node")
            remaining = 64 - len(goal.state.get("nodes", {}))
            if remaining < 1:
                raise GoalError("Goal has no remaining node capacity for a recovery plan")

            request = current_request_context()
            runtime = request.runtime if request is not None else None
            if runtime is None:
                raise GoalError("Recovery Planner requires the active model runtime")
            try:
                response = await runtime.provider.chat_with_retry(
                    messages=build_recovery_messages(goal, blocked_node_id, min(remaining, 16)),
                    tools=[_SUBMIT_TOOL],
                    model=runtime.model,
                    max_tokens=min(runtime.generation.max_tokens, 4096),
                    temperature=0,
                    reasoning_effort=runtime.generation.reasoning_effort,
                    tool_choice="required",
                    retry_mode="standard",
                )
            except Exception as exc:
                return ToolResult.error(f"Error: Recovery Planner model call failed: {exc}")
            goal = await asyncio.to_thread(
                store.apply,
                goal.id,
                expected_version,
                {"action": "recovery_attempt", "node_id": blocked_node_id},
            )
            self._save(session, goal)
            proposal = _proposal_from_response(response)
            if len(proposal["nodes"]) > remaining:
                raise GoalError("Recovery Planner proposed more nodes than the Goal can retain")
            updated = await asyncio.to_thread(
                store.apply,
                goal.id,
                goal.version,
                {
                    "action": "replan",
                    "node_id": blocked_node_id,
                    "nodes": proposal["nodes"],
                    "rationale": proposal["rationale"],
                },
            )
            self._save(session, updated)
            return self._result(updated)
        except (GoalConflictError, GoalError, TypeError, ValueError) as exc:
            return ToolResult.error(f"Error: Goal recovery replan was rejected: {exc}")


def build_recovery_messages(goal: Goal, blocked_node_id: str, max_nodes: int) -> list[dict[str, str]]:
    nodes: Mapping[str, Mapping[str, Any]] = goal.state["nodes"]
    target = nodes[blocked_node_id]
    predecessors = _successful_predecessors(nodes, target)
    failures = [
        {
            "id": node["id"],
            "title": node["title"],
            "failure": str(node.get("failure") or "")[:1000],
        }
        for node in nodes.values()
        if node.get("failure")
    ][-8:]
    statuses: dict[str, int] = {}
    for node in nodes.values():
        status = str(node["status"])
        statuses[status] = statuses.get(status, 0) + 1
    evidence = {
        "schema": 1,
        "ultimate_objective": str(goal.state.get("objective") or ""),
        "blocked_path": {
            "id": target["id"],
            "title": target["title"],
            "required_outcome": target["outcome"],
            "failure": str(target.get("failure") or "")[:2000],
        },
        "successful_predecessors": predecessors,
        "failure_experience": failures,
        "progress_summary": {
            "label": goal.summary,
            "plan_revision": goal.state.get("revision", 0),
            "status_counts": statuses,
            "retained_nodes": [
                {"id": node["id"], "title": node["title"], "status": node["status"]}
                for node in nodes.values()
                if node["status"] != "superseded"
            ][:24],
        },
        "constraints": {
            "max_replacement_nodes": max_nodes,
            "existing_node_ids": list(nodes),
            "allowed_existing_dependencies": [
                node_id for node_id, node in nodes.items() if node["status"] == "succeeded"
            ],
        },
    }
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
    ]


def _successful_predecessors(
    nodes: Mapping[str, Mapping[str, Any]],
    target: Mapping[str, Any],
) -> list[dict[str, str]]:
    pending = list(target.get("depends_on", []))
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    while pending and len(results) < 16:
        node_id = pending.pop(0)
        if node_id in seen or node_id not in nodes:
            continue
        seen.add(node_id)
        node = nodes[node_id]
        pending.extend(node.get("depends_on", []))
        if node.get("status") == "succeeded":
            results.append(
                {
                    "id": node_id,
                    "title": str(node.get("title") or "")[:300],
                    "outcome": str(node.get("outcome") or "")[:1000],
                    "result": str(node.get("result") or "")[:2000],
                }
            )
    return results


def _proposal_from_response(response: Any) -> dict[str, Any]:
    calls = [call for call in response.tool_calls if call.name == "submit_recovery_plan"]
    if len(calls) != 1:
        raise GoalError("Recovery Planner did not return exactly one structured proposal")
    proposal = parse_tool_arguments(calls[0].arguments)
    if not isinstance(proposal, dict):
        raise GoalError("Recovery Planner proposal is not a JSON object")
    errors = Schema.validate_json_schema_value(proposal, _SUBMIT_PARAMETERS)
    if errors:
        raise GoalError("invalid Recovery Planner proposal: " + "; ".join(errors[:3]))
    return proposal
