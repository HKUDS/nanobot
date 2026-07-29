from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.goal_permission import goal_mutation_permission
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.goal_plan import PlanGoalTool, UpdateGoalNodeTool
from nanobot.agent.tools.goal_replan import ReplanGoalTool
from nanobot.agent.tools.long_task import CreateGoalTool
from nanobot.goals import GoalStore
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager
from nanobot.utils.llm_runtime import LLMRuntime


def _runtime(response: LLMResponse) -> tuple[LLMRuntime, AsyncMock]:
    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=response)
    runtime = LLMRuntime(
        provider=provider,
        model="test-model",
        generation=GenerationSettings(temperature=0.7, max_tokens=2048),
        context_window_tokens=32_000,
    )
    return runtime, provider.chat_with_retry


def _context(runtime: LLMRuntime) -> RequestContext:
    return RequestContext(
        channel="websocket",
        chat_id="c1",
        session_key="websocket:c1",
        original_user_text="SECRET ORIGINAL CHAT MUST NOT BE COPIED",
        runtime=runtime,
        metadata={"goal_requested": True, "original_command": "/goal"},
    )


def _proposal_response() -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="recovery",
                name="submit_recovery_plan",
                arguments={
                    "rationale": "Use the verified preparation with a different endpoint.",
                    "nodes": [
                        {
                            "id": "alternate",
                            "title": "Alternate route",
                            "outcome": "Artifact",
                            "depends_on": ["prep"],
                        }
                    ],
                },
            )
        ],
        finish_reason="tool_calls",
    )


async def _blocked_goal(sm: SessionManager, runtime: LLMRuntime):
    root = sm.workspace / "test-goals"
    common = {"sessions": sm, "workspace": sm.workspace, "goal_store_root": root}
    create = CreateGoalTool(**common)
    plan = PlanGoalTool(**common)
    node = UpdateGoalNodeTool(**common)
    replan = ReplanGoalTool(**common)
    ctx = _context(runtime)
    with request_context(ctx), goal_mutation_permission(True):
        await create.execute(objective="Build through a recoverable route", ui_summary="recover")
    with request_context(ctx):
        await plan.execute(
            expected_version=1,
            nodes=[
                {"id": "prep", "title": "Prepare", "outcome": "Ready", "depends_on": []},
                {
                    "id": "primary",
                    "title": "Primary route",
                    "outcome": "Artifact",
                    "depends_on": ["prep"],
                },
                {
                    "id": "finish",
                    "title": "Finish",
                    "outcome": "Done",
                    "depends_on": ["primary"],
                },
                {"id": "other", "title": "Other", "outcome": "Done", "depends_on": []},
            ],
        )
        await node.execute(expected_version=2, node_id="prep", action="begin")
        await node.execute(
            expected_version=3,
            node_id="prep",
            action="succeed",
            result="Preparation verified",
        )
        await node.execute(expected_version=4, node_id="primary", action="begin")
        await node.execute(
            expected_version=5,
            node_id="primary",
            action="block",
            reason="Primary endpoint is unavailable",
        )
    store = GoalStore.for_workspace(sm.workspace, root=root)
    ref = sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]
    return replan, ctx, store, ref


@pytest.mark.asyncio
async def test_recovery_planner_uses_clean_evidence_and_atomically_replaces_path(tmp_path) -> None:
    runtime, planner_call = _runtime(_proposal_response())
    sm = SessionManager(tmp_path)
    replan, ctx, store, ref = await _blocked_goal(sm, runtime)

    with request_context(ctx):
        result = json.loads(await replan.execute(expected_version=6, blocked_node_id="primary"))

    goal = store.get(ref["goal_id"])
    assert goal is not None
    assert goal.state["nodes"]["primary"]["status"] == "superseded"
    assert goal.state["nodes"]["alternate"]["status"] == "ready"
    assert goal.state["nodes"]["finish"]["depends_on"] == ["alternate"]
    assert goal.state["nodes"]["other"]["status"] == "ready"
    assert result["needs_replan"] is False
    assert sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]["version"] == 8
    assert goal.state["recovery_attempts"] == 0

    kwargs = planner_call.await_args.kwargs
    assert [message["role"] for message in kwargs["messages"]] == ["system", "user"]
    evidence = json.loads(kwargs["messages"][1]["content"])
    assert evidence["ultimate_objective"] == "Build through a recoverable route"
    assert evidence["successful_predecessors"][0]["result"] == "Preparation verified"
    assert evidence["failure_experience"][0]["failure"] == "Primary endpoint is unavailable"
    assert "SECRET ORIGINAL CHAT" not in kwargs["messages"][1]["content"]
    assert [tool["function"]["name"] for tool in kwargs["tools"]] == [
        "submit_recovery_plan"
    ]
    assert kwargs["tool_choice"] == "required"


@pytest.mark.asyncio
async def test_invalid_recovery_proposal_consumes_budget_but_keeps_blocked_path(tmp_path) -> None:
    runtime, planner_call = _runtime(LLMResponse(content='{"nodes": []}', tool_calls=[]))
    sm = SessionManager(tmp_path)
    replan, ctx, store, ref = await _blocked_goal(sm, runtime)

    with request_context(ctx):
        result = await replan.execute(expected_version=6, blocked_node_id="primary")

    goal = store.get(ref["goal_id"])
    assert "did not return exactly one structured proposal" in str(result)
    assert goal is not None and goal.version == 7
    assert goal.state["recovery_attempts"] == 1
    assert goal.state["nodes"]["primary"]["status"] == "blocked"
    assert goal.state["needs_replan"] is True
    planner_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_failure_does_not_consume_recovery_budget(tmp_path) -> None:
    runtime, planner_call = _runtime(LLMResponse(content=None))
    planner_call.side_effect = RuntimeError("provider unavailable")
    sm = SessionManager(tmp_path)
    replan, ctx, store, ref = await _blocked_goal(sm, runtime)

    with request_context(ctx):
        result = await replan.execute(expected_version=6, blocked_node_id="primary")

    goal = store.get(ref["goal_id"])
    assert "provider unavailable" in str(result)
    assert goal is not None and goal.version == 6
    assert goal.state["recovery_attempts"] == 0


@pytest.mark.asyncio
async def test_stale_replan_is_rejected_before_calling_model(tmp_path) -> None:
    runtime, planner_call = _runtime(LLMResponse(content=None))
    sm = SessionManager(tmp_path)
    replan, ctx, store, ref = await _blocked_goal(sm, runtime)

    with request_context(ctx):
        result = await replan.execute(expected_version=5, blocked_node_id="primary")

    assert "expected 5" in str(result)
    assert store.get(ref["goal_id"]).version == 6
    planner_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_goal_change_wins_over_slow_recovery_proposal(tmp_path) -> None:
    runtime, planner_call = _runtime(_proposal_response())
    sm = SessionManager(tmp_path)
    replan, ctx, store, ref = await _blocked_goal(sm, runtime)

    async def change_goal_before_proposal_returns(**_kwargs):
        store.apply(ref["goal_id"], 6, {"action": "begin", "node_id": "other"})
        return _proposal_response()

    planner_call.side_effect = change_goal_before_proposal_returns
    with request_context(ctx):
        result = await replan.execute(expected_version=6, blocked_node_id="primary")

    goal = store.get(ref["goal_id"])
    assert "goal is at version 7, expected 6" in str(result)
    assert goal is not None and goal.state["nodes"]["primary"]["status"] == "blocked"
    assert "alternate" not in goal.state["nodes"]
    assert goal.state["nodes"]["other"]["status"] == "running"
