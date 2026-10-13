"""Sustained goals close only after the frozen criteria pass independent review."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.completion import completion_evidence_scope
from nanobot.agent.goal_permission import goal_mutation_permission
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.long_task import CreateGoalTool, UpdateGoalTool
from nanobot.agent.tools.registry import is_tool_error_result
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager
from nanobot.utils.llm_runtime import LLMRuntime


def setup_goal(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    provider.provider_name = "test"
    provider.get_default_model.return_value = "test-model"
    provider.estimate_prompt_tokens = MagicMock(return_value=(100, "test"))
    runtime = LLMRuntime.capture(provider, "test-model", context_window_tokens=128_000)
    sessions = SessionManager(tmp_path)
    context = RequestContext("cli", "goal", session_key="cli:goal", runtime=runtime)
    return sessions, provider, context, CreateGoalTool(sessions), UpdateGoalTool(sessions)


def review(status, *, reason="The required output is absent.", evidence_ids=("candidate",)):
    return LLMResponse(content=json.dumps({
        "status": status, "reason": reason, "evidence_ids": list(evidence_ids),
    }))


def call(call_id, name, **arguments):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(call_id, name, arguments)])


@pytest.mark.asyncio
async def test_goal_repairs_rejected_claim_using_current_run_file_receipts(tmp_path):
    _sessions, provider, _context, _create, _update = setup_goal(tmp_path)
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        call("create", "create_goal", objective="Create result.txt", acceptance_criteria="result.txt contains answer=42 and has been read back."),
        call("premature", "update_goal", action="complete", recap="Done."),
        call("write", "write_file", path="result.txt", content="answer=42"),
        call("read", "read_file", path="result.txt"),
        call("finish", "update_goal", action="complete", recap="Wrote and read back answer=42."),
        call("late-write", "write_file", path="result.txt", content="invalidated after review"),
    ])
    provider.chat_with_retry = AsyncMock(side_effect=[
        review("needs_revision"),
        review("verified", reason="Readback matches the frozen criteria.", evidence_ids=("read",)),
    ])
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    try:
        response = await loop._process_message(InboundMessage(
            channel="cli", sender_id="user", chat_id="goal",
            content="/goal Write answer=42 to result.txt, read it back, and independently verify completion.",
        ))
    finally:
        await loop.subagents.close()

    assert response.content == "Wrote and read back answer=42."
    assert (tmp_path / "result.txt").read_text() == "answer=42"
    goal = loop.sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]
    assert goal["status"] == "completed"
    assert goal["completion"]["status"] == "verified"
    assert goal["verification_attempts"] == 2
    assert provider.chat_with_retry.await_count == 2
    assert provider.chat_stream_with_retry.await_count == 5
    first_payload = json.loads(provider.chat_with_retry.await_args_list[0].kwargs["messages"][1]["content"])
    assert not any(item["id"] == "read" for item in first_payload["evidence"])
    second_payload = json.loads(provider.chat_with_retry.await_args_list[1].kwargs["messages"][1]["content"])
    assert any(item["id"] == "read" and "answer=42" in item["result"] for item in second_payload["evidence"])


@pytest.mark.asyncio
async def test_repeated_rejection_blocks_goal_and_survives_session_reload(tmp_path):
    sessions, provider, context, create, update = setup_goal(tmp_path)
    provider.chat_with_retry = AsyncMock(return_value=review("needs_revision"))
    with request_context(context), goal_mutation_permission(True), completion_evidence_scope([]):
        await create.execute(objective="Create a report", acceptance_criteria="Report contains measured results.")
        await update.execute(action="complete", recap="Done.")
        first = sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]
        assert first["status"] == "active"
        assert first["completion"]["status"] == "needs_revision"
        await update.execute(action="complete", recap="Still done.")
        await update.execute(action="complete", recap="Try again.")

    goal = SessionManager(tmp_path).get_or_create("cli:goal").metadata[GOAL_STATE_KEY]
    assert goal["status"] == "blocked"
    assert goal["completion"]["status"] == "exhausted"
    assert goal["verification_attempts"] == 2
    assert "completed_at" not in goal
    assert provider.chat_with_retry.await_count == 2


@pytest.mark.asyncio
async def test_invalid_review_never_commits_completed_goal(tmp_path):
    sessions, provider, context, create, update = setup_goal(tmp_path)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="probably fine"))
    with request_context(context), goal_mutation_permission(True), completion_evidence_scope([]):
        await create.execute(objective="Deliver report", acceptance_criteria="Report exists.")
        await update.execute(action="complete", recap="Done.")

    goal = sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]
    assert goal["status"] == "blocked"
    assert goal["completion"]["status"] == "blocked"
    assert "completed_at" not in goal


@pytest.mark.asyncio
async def test_goal_criteria_cannot_be_weakened_by_completion_request(tmp_path):
    sessions, provider, context, create, update = setup_goal(tmp_path)
    provider.chat_with_retry = AsyncMock(return_value=review("needs_revision"))
    with request_context(context), goal_mutation_permission(True), completion_evidence_scope([]):
        await create.execute(objective="Deliver report", acceptance_criteria="Report has ten verified sources.")
        await update.execute(action="complete", recap="Done.", acceptance_criteria="Say done.")

    goal = sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]
    assert goal["acceptance_criteria"] == "Report has ten verified sources."
    assert goal["status"] != "completed"
    for request in provider.chat_with_retry.await_args_list:
        assert "Report has ten verified sources." in str(request.kwargs["messages"])
        assert "Say done." not in str(request.kwargs["messages"])


@pytest.mark.asyncio
async def test_explicit_replacement_gets_new_criteria_and_review_budget(tmp_path):
    sessions, provider, context, create, update = setup_goal(tmp_path)
    provider.chat_with_retry = AsyncMock(return_value=review("needs_revision"))
    with request_context(context), goal_mutation_permission(True), completion_evidence_scope([]):
        await create.execute(objective="Old report", acceptance_criteria="Ten sources.")
        await update.execute(action="complete", recap="Done.")
    with request_context(context), goal_mutation_permission(True):
        await update.execute(action="replace", objective="New report", acceptance_criteria="Three sources.")

    goal = sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]
    assert goal["status"] == "active"
    assert goal["objective"] == "New report"
    assert goal["acceptance_criteria"] == "Three sources."
    assert goal.get("verification_attempts", 0) == 0
    assert goal.get("completion") is None


@pytest.mark.asyncio
async def test_goal_cannot_complete_without_current_execution_evidence_scope(tmp_path):
    sessions, provider, context, create, update = setup_goal(tmp_path)
    provider.chat_with_retry = AsyncMock(return_value=review("verified"))
    with request_context(context), goal_mutation_permission(True):
        await create.execute(objective="Deliver report", acceptance_criteria="Report exists.")
        await update.execute(action="complete", recap="Done.")

    assert sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]["status"] != "completed"
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_builder_cannot_remove_criteria_by_replacing_goal_in_same_turn(tmp_path):
    sessions, provider, context, create, update = setup_goal(tmp_path)
    provider.chat_with_retry = AsyncMock()
    with request_context(context), goal_mutation_permission(True):
        await create.execute(objective="Deliver report", acceptance_criteria="Ten verified sources.")
        result = await update.execute(action="replace", objective="Just say done")

    assert is_tool_error_result(result)
    goal = sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]
    assert goal["objective"] == "Deliver report"
    assert goal["acceptance_criteria"] == "Ten verified sources."
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_cannot_review_before_other_calls_in_its_batch_finish(tmp_path):
    sessions, provider, context, create, update = setup_goal(tmp_path)
    provider.chat_with_retry = AsyncMock(return_value=review("verified"))
    messages = []
    with request_context(context), goal_mutation_permission(True), completion_evidence_scope(messages):
        await create.execute(objective="Write report", acceptance_criteria="Report exists.")
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            ToolCallRequest("write", "write_file", {"path": "report.txt", "content": "report"}).to_openai_tool_call(),
            ToolCallRequest("finish", "update_goal", {"action": "complete", "recap": "Done."}).to_openai_tool_call(),
        ]})
        result = await update.execute(action="complete", recap="Done.")

    assert is_tool_error_result(result)
    assert sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]["status"] == "active"
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "replace"])
async def test_review_cannot_overwrite_goal_changed_while_judge_was_running(tmp_path, action):
    sessions, provider, context, create, update = setup_goal(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_review(**_kwargs):
        started.set()
        await release.wait()
        return review("verified", reason="Text meets the criteria.")

    provider.chat_with_retry = AsyncMock(side_effect=delayed_review)
    with request_context(context), goal_mutation_permission(True), completion_evidence_scope([]):
        await create.execute(objective="Write a greeting", acceptance_criteria="Greeting says hello.")
        pending = asyncio.create_task(update.execute(action="complete", recap="Hello!"))
        await asyncio.wait_for(started.wait(), timeout=1)
        with goal_mutation_permission(True):
            await update.execute(action=action, objective="New goal" if action == "replace" else None)
        release.set()
        result = await asyncio.wait_for(pending, timeout=1)

    assert is_tool_error_result(result)
    goal = sessions.get_or_create("cli:goal").metadata[GOAL_STATE_KEY]
    assert goal["status"] == ("cancelled" if action == "cancel" else "active")
    assert "completed_at" not in goal
    if action == "replace":
        assert goal["objective"] == "New goal"
