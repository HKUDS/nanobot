from __future__ import annotations

import json

import pytest

from nanobot.agent.goal_permission import goal_mutation_permission
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.goal_plan import (
    ExpandGoalNodeTool,
    GetGoalPlanTool,
    PlanGoalTool,
    UpdateGoalNodeTool,
)
from nanobot.agent.tools.long_task import CreateGoalTool, UpdateGoalTool
from nanobot.goals import GoalStore
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager


def _context() -> RequestContext:
    return RequestContext(
        channel="websocket",
        chat_id="c1",
        session_key="websocket:c1",
        metadata={"goal_requested": True, "original_command": "/goal"},
    )


def _tools(sm: SessionManager):
    root = sm.workspace / "test-goals"
    common = {"sessions": sm, "workspace": sm.workspace, "goal_store_root": root}
    return (
        CreateGoalTool(**common),
        UpdateGoalTool(**common),
        PlanGoalTool(**common),
        UpdateGoalNodeTool(**common),
        GetGoalPlanTool(**common),
        GoalStore.for_workspace(sm.workspace, root=root),
    )


async def _create(create: CreateGoalTool) -> None:
    with request_context(_context()), goal_mutation_permission(True):
        result = await create.execute(objective="Build and publish", ui_summary="ship")
    assert "recorded durably" in result


def _nodes() -> list[dict]:
    return [
        {"id": "build", "title": "Build", "outcome": "Artifact exists", "depends_on": []},
        {
            "id": "publish",
            "title": "Publish",
            "outcome": "Artifact is published",
            "depends_on": ["build"],
        },
    ]


@pytest.mark.asyncio
async def test_goal_tools_execute_graph_and_keep_session_reference_compact(tmp_path) -> None:
    sm = SessionManager(tmp_path)
    create, update, plan, node, get_plan, store = _tools(sm)
    await _create(create)

    with request_context(_context()):
        planned = json.loads(await plan.execute(expected_version=1, nodes=_nodes()))
        started = json.loads(
            await node.execute(expected_version=2, node_id="build", action="begin")
        )
        succeeded = json.loads(
            await node.execute(
                expected_version=3,
                node_id="build",
                action="succeed",
                result="focused tests passed",
            )
        )
        queried = json.loads(await get_plan.execute())

    assert [item["id"] for item in planned["frontier"]] == ["build"]
    assert started["running"][0]["id"] == "build"
    assert [item["id"] for item in succeeded["frontier"]] == ["publish"]
    assert queried == succeeded
    ref = sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]
    assert set(ref) == {
        "schema",
        "goal_id",
        "workspace",
        "status",
        "version",
        "objective",
        "ui_summary",
    }
    assert "nodes" not in ref
    assert store.get(ref["goal_id"]).state["objective"] == "Build and publish"

    with request_context(_context()), goal_mutation_permission(True):
        rejected = await update.execute(action="complete", recap="Not finished")
    assert "every retained node succeeds" in str(rejected)


@pytest.mark.asyncio
async def test_block_tool_keeps_goal_active_and_independent_node_ready(tmp_path) -> None:
    sm = SessionManager(tmp_path)
    create, _update, plan, node, _get_plan, _store = _tools(sm)
    await _create(create)
    independent = [
        {"id": "primary", "title": "Primary", "outcome": "Done", "depends_on": []},
        {"id": "other", "title": "Other", "outcome": "Done", "depends_on": []},
    ]

    with request_context(_context()):
        await plan.execute(expected_version=1, nodes=independent)
        await node.execute(expected_version=2, node_id="primary", action="begin")
        blocked = json.loads(
            await node.execute(
                expected_version=3,
                node_id="primary",
                action="block",
                reason="path is infeasible",
            )
        )

    assert blocked["status"] == "active"
    assert blocked["needs_replan"] is True
    assert [item["id"] for item in blocked["frontier"]] == ["other"]
    assert sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]["status"] == "active"


@pytest.mark.asyncio
async def test_runtime_context_resolves_authoritative_store_projection(tmp_path) -> None:
    sm = SessionManager(tmp_path)
    create, _update, plan, _node, _get_plan, _store = _tools(sm)
    await _create(create)
    with request_context(_context()):
        await plan.execute(expected_version=1, nodes=_nodes())
        context = await create._provide_runtime_context(_context())

    assert context is not None
    assert "Build and publish" in context.content
    assert "build (Build)" in context.content
    assert "version 2" in context.content


@pytest.mark.asyncio
async def test_node_commands_require_current_version_and_valid_transition(tmp_path) -> None:
    sm = SessionManager(tmp_path)
    create, _update, plan, node, _get_plan, _store = _tools(sm)
    await _create(create)
    with request_context(_context()):
        await plan.execute(expected_version=1, nodes=_nodes())
        stale = await node.execute(expected_version=1, node_id="build", action="begin")
        invalid = await node.execute(expected_version=2, node_id="publish", action="begin")

    assert "expected 1" in str(stale)
    assert "only a ready node" in str(invalid)


@pytest.mark.asyncio
async def test_expand_goal_node_refines_coarse_work_without_replanning(tmp_path) -> None:
    sm = SessionManager(tmp_path)
    create, _update, plan, _node, _get_plan, _store = _tools(sm)
    expand = ExpandGoalNodeTool(
        sessions=sm,
        workspace=sm.workspace,
        goal_store_root=sm.workspace / "test-goals",
    )
    await _create(create)
    with request_context(_context()):
        planned = json.loads(
            await plan.execute(
                expected_version=1,
                nodes=[
                    {
                        "id": "coarse",
                        "title": "Determine implementation",
                        "outcome": "Feature exists",
                        "kind": "coarse",
                        "depends_on": [],
                    },
                    {
                        "id": "publish",
                        "title": "Publish",
                        "outcome": "Published",
                        "depends_on": ["coarse"],
                    },
                ],
            )
        )
        context = await create._provide_runtime_context(_context())
        expanded = json.loads(
            await expand.execute(
                expected_version=2,
                node_id="coarse",
                nodes=[
                    {
                        "id": "implement",
                        "title": "Implement",
                        "outcome": "Feature exists",
                        "depends_on": [],
                    }
                ],
            )
        )

    assert [node["id"] for node in planned["expandable"]] == ["coarse"]
    assert planned["frontier"] == []
    assert context is not None and "Expandable: coarse" in context.content
    assert [node["id"] for node in expanded["frontier"]] == ["implement"]
    assert expanded["needs_replan"] is False
    assert sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]["version"] == 3
