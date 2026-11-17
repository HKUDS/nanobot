import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.goal_permission import goal_mutation_allowed
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import GoalStateChanged
from nanobot.goal.assembly import install_goal
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager


@pytest.fixture
async def goal_loop(tmp_path):
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    loop = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model",
        builtin_assembly=install_goal,
    )
    session = await loop.sessions.state.get("cli:goal-failure")
    await loop.sessions.state.update_metadata(session.key, {
        GOAL_STATE_KEY: {
            "status": "active", "objective": "Verify the synthetic task.",
            "ui_summary": "Synthetic task", "started_at": "2026-01-01T00:00:00",
        },
    })
    try:
        yield loop, provider, session.key
    finally:
        await loop.aclose()


@pytest.mark.parametrize("tail", ["", "Still incomplete."])
async def test_exhausted_length_recovery_blocks_and_persists_goal(goal_loop, tmp_path, tail):
    loop, provider, key = goal_loop
    changes = []
    loop.bus.subscribe(changes.append, GoalStateChanged)
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="Working.", finish_reason="length"),
        LLMResponse(content="", finish_reason="length"),
        LLMResponse(content="", finish_reason="length"),
        LLMResponse(content=tail, finish_reason="length"),
    ])

    result = await loop.process_direct("Continue the task.", session_key=key)

    saved = await loop.sessions.state.read_header(key)
    goal = saved.metadata[GOAL_STATE_KEY]
    assert goal["status"] == "blocked"
    assert goal["blocked_reason"] == "length"
    assert "output limit" in goal["recap"]
    assert goal["objective"] == "Verify the synthetic task."
    assert goal["started_at"] == "2026-01-01T00:00:00"
    assert goal["ended_at"]
    assert result.content == ("Working.Still incomplete." if tail else
                              "Model output limit reached; continuation attempts were exhausted.")
    assert provider.chat_stream_with_retry.await_count == 4
    assert len(changes) == 1
    assert changes[0].session_metadata[GOAL_STATE_KEY] == goal
    assert SessionManager(tmp_path).get_or_create(key).metadata[GOAL_STATE_KEY] == goal


async def test_user_can_resume_same_goal_and_complete_it(goal_loop):
    loop, provider, key = goal_loop
    await loop.sessions.state.mutate_metadata(key, lambda metadata: metadata[GOAL_STATE_KEY].update({
        "status": "blocked", "blocked_reason": "length", "ended_at": "2026-01-02T00:00:00",
        "recap": "Output limit reached.",
    }))
    requests = []

    async def respond(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            assert "Blocked: Output limit reached." in str(kwargs["messages"])
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="resume", name="update_goal", arguments={"action": "resume"},
            )])
        if len(requests) == 2:
            goal = (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]
            assert goal["status"] == "active"
            assert goal_mutation_allowed() is False
            assert goal["started_at"] == "2026-01-01T00:00:00"
            assert goal["objective"] == "Verify the synthetic task."
            assert "ended_at" not in goal and "blocked_reason" not in goal
            return LLMResponse(content="One more check.")
        if len(requests) == 3:
            assert "Please continue working toward the objective" in str(kwargs["messages"])
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="complete", name="update_goal", arguments={"action": "complete", "recap": "Verified."},
            )])
        assert len(requests) == 4
        return LLMResponse(content="Verified.")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    result = await loop.process_direct("Please resume the blocked goal.", session_key=key)
    goal = (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]
    assert result.content == "Verified."
    assert goal["status"] == "completed"
    assert goal["resumed_at"]


@pytest.mark.parametrize("finish_reason", ["error", "refusal", "content_filter", "empty"])
async def test_terminal_model_failure_blocks_after_recovery(goal_loop, finish_reason):
    loop, provider, key = goal_loop
    observed = []

    async def committed(event):
        current = await loop.sessions.state.read_header(key)
        observed.append((event, current.metadata[GOAL_STATE_KEY]))

    loop.bus.subscribe(committed, GoalStateChanged)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(
        content="" if finish_reason == "empty" else "Model stopped.",
        finish_reason="stop" if finish_reason == "empty" else finish_reason,
    ))
    await loop.process_direct("Continue", session_key=key)
    goal = (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]
    assert goal["status"] == "blocked"
    assert goal["blocked_reason"] == ("empty_final_response" if finish_reason == "empty" else finish_reason)
    assert len(observed) == 1
    event, committed_goal = observed[0]
    assert event.session_metadata[GOAL_STATE_KEY] == committed_goal == goal
    assert event.context.session_generation == (await loop.sessions.state.read_header(key)).generation
    assert provider.chat_stream_with_retry.await_count == (3 if finish_reason == "empty" else 1)


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_exception_blocks_but_cancellation_keeps_goal_active(goal_loop, error):
    loop, provider, key = goal_loop
    provider.chat_stream_with_retry = AsyncMock(side_effect=error("synthetic failure"))
    with pytest.raises(error):
        await loop.process_direct("Continue", session_key=key)
    goal = (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]
    if error is RuntimeError:
        assert goal["status"] == "blocked" and goal["blocked_reason"] == "exception"
    else:
        assert goal["status"] == "active"


async def test_successful_recovery_keeps_goal_active_until_model_closes_it(goal_loop):
    loop, provider, key = goal_loop
    changes = []
    loop.bus.subscribe(changes.append, GoalStateChanged)
    calls = 0

    async def respond(**kwargs):
        nonlocal calls
        calls += 1
        goal = (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]
        assert goal["status"] == ("completed" if calls == 4 else "active")
        if calls == 1:
            return LLMResponse(content="Partial ", finish_reason="length")
        if calls == 2:
            return LLMResponse(content="answer.")
        if calls == 3:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="done", name="update_goal", arguments={"action": "complete", "recap": "Verified."},
            )])
        return LLMResponse(content="Verified.")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    await loop.process_direct("Continue", session_key=key)
    assert calls == 4
    assert [event.session_metadata[GOAL_STATE_KEY]["status"] for event in changes] == ["completed"]


@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_failure_cannot_overwrite_a_goal_closed_during_execution(goal_loop, status):
    loop, provider, key = goal_loop

    async def respond(**kwargs):
        await loop.sessions.state.mutate_metadata(key, lambda metadata: metadata[GOAL_STATE_KEY].update({
            "status": status, "recap": "Closed by another control action.",
        }))
        return LLMResponse(content="Model stopped.", finish_reason="error")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    await loop.process_direct("Continue", session_key=key)
    goal = (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]
    assert goal["status"] == status
    assert goal["recap"] == "Closed by another control action."


@pytest.mark.parametrize("message", [
    InboundMessage(channel="cli", sender_id="user", chat_id="goal-failure", content="What is its status?"),
    InboundMessage(channel="cli", sender_id="cron", chat_id="goal-failure", content="Scheduled check.",
                   metadata={"_cron_trigger": {"job_id": "synthetic-job"}}),
])
async def test_incoming_message_does_not_automatically_resume_a_blocked_goal(goal_loop, message):
    loop, provider, key = goal_loop
    await loop.sessions.state.mutate_metadata(key, lambda metadata: metadata[GOAL_STATE_KEY].update({
        "status": "blocked", "recap": "Waiting for user.",
    }))
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="The goal is blocked."))
    await loop._process_message(message, session_key=key)
    assert (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]["status"] == "blocked"
    provider.chat_stream_with_retry.assert_awaited_once()


async def test_automated_input_cannot_resume_a_blocked_goal(goal_loop):
    loop, provider, key = goal_loop
    await loop.sessions.state.mutate_metadata(key, lambda metadata: metadata[GOAL_STATE_KEY].update({
        "status": "blocked", "recap": "Waiting for user.",
    }))
    requests = []

    async def respond(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="resume", name="update_goal", arguments={"action": "resume"},
            )])
        assert "requires a fresh user request" in str(kwargs["messages"][-1])
        return LLMResponse(content="Waiting for the user.")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    await loop._process_message(InboundMessage(
        channel="cli", sender_id="cron", chat_id="goal-failure", content="Scheduled check.",
        metadata={"_cron_trigger": {"job_id": "synthetic-job"}},
    ), session_key=key)
    assert len(requests) == 2
    assert (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]["status"] == "blocked"


async def test_resume_cannot_overwrite_concurrent_user_cancellation(goal_loop, monkeypatch):
    loop, provider, key = goal_loop
    await loop.sessions.state.mutate_metadata(key, lambda metadata: metadata[GOAL_STATE_KEY].update({
        "status": "blocked", "recap": "Waiting for user.",
    }))
    mutate = loop.sessions.state.mutate_metadata

    async def cancel_before_commit(session_key, change, **kwargs):
        await mutate(session_key, lambda metadata: metadata[GOAL_STATE_KEY].update({"status": "cancelled"}))
        return await mutate(session_key, change, **kwargs)

    monkeypatch.setattr(loop.sessions.state, "mutate_metadata", cancel_before_commit)
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="resume", name="update_goal", arguments={"action": "resume"},
        )]),
        LLMResponse(content="The goal was cancelled."),
    ])
    await loop.process_direct("Please resume the goal.", session_key=key)
    goal = (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]
    assert goal["status"] == "cancelled"
    messages = provider.chat_stream_with_retry.call_args.kwargs["messages"]
    assert "changed before resumption could be committed" in str(messages)


async def test_prompt_build_failure_blocks_goal_before_the_first_model_call(goal_loop, monkeypatch):
    loop, provider, key = goal_loop
    monkeypatch.setattr(loop, "_build_turn", AsyncMock(side_effect=RuntimeError("synthetic prompt failure")))
    with pytest.raises(RuntimeError, match="synthetic prompt failure"):
        await loop.process_direct("Continue", session_key=key)
    goal = (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]
    assert goal["status"] == "blocked" and goal["blocked_reason"] == "exception"
    provider.chat_stream_with_retry.assert_not_called()


async def test_ephemeral_failure_does_not_block_the_durable_goal(goal_loop):
    loop, provider, key = goal_loop
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Model stopped.", finish_reason="error"))
    await loop._process_message(InboundMessage(
        channel="cli", sender_id="user", chat_id="goal-failure", content="One temporary request.",
    ), session_key=key, ephemeral=True)
    assert (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]["status"] == "active"


async def test_recoverable_tool_error_does_not_block_the_goal(goal_loop):
    loop, provider, key = goal_loop
    calls = 0

    async def respond(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="read", name="read_file", arguments={"path": "missing-synthetic-file.txt"},
            )])
        if calls == 2:
            assert "not found" in str(kwargs["messages"][-1]).lower()
            assert (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]["status"] == "active"
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="done", name="update_goal", arguments={"action": "complete", "recap": "Verified without that file."},
            )])
        return LLMResponse(content="Verified.")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    await loop.process_direct("Continue", session_key=key)
    assert calls == 3
    assert (await loop.sessions.state.read_header(key)).metadata[GOAL_STATE_KEY]["status"] == "completed"
