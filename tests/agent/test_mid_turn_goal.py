"""Explicit goal requests can steer a running session without restarting it."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.goal_permission import goal_mutation_allowed
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
from nanobot.runtime_context import public_history_messages
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import SessionManager


@pytest.mark.parametrize("command", ["/goal execute the agreed plan", "/GOAL@nanobot execute the agreed plan"])
async def test_goal_input_enters_running_turn_with_scoped_permission(tmp_path, command):
    first_call = asyncio.Event()
    release = asyncio.Event()
    calls = []
    permissions = []
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")

    async def respond(**kwargs):
        calls.append(str(kwargs["messages"]))
        permissions.append(goal_mutation_allowed())
        if len(calls) == 1:
            first_call.set()
            await release.wait()
            return LLMResponse(content="The plan is to verify the migration.")
        if len(calls) == 2:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="create", name="create_goal",
                arguments={"objective": "Verify the migration as agreed in this conversation."},
            )])
        if len(calls) == 3:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="complete", name="update_goal",
                arguments={"action": "complete", "recap": "Migration verified."},
            )])
        if len(calls) == 4:
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="unauthorized", name="create_goal",
                arguments={"objective": "Start another task without permission."},
            )])
        return LLMResponse(content="done")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    process = AsyncMock(wraps=loop._process_message)
    loop._process_message = process
    run = asyncio.create_task(loop.run())
    try:
        await loop.bus.publish_inbound(InboundMessage(
            channel="cli", sender_id="user", chat_id="test", content="Discuss the migration.",
        ))
        await asyncio.wait_for(first_call.wait(), 3)
        await loop.bus.publish_inbound(InboundMessage(
            channel="cli", sender_id="user", chat_id="test", content=command,
        ))
        async with asyncio.timeout(3):
            while loop._pending_queues["cli:test"].empty():
                await asyncio.sleep(0)
        assert len(calls) == 1
        release.set()
        await asyncio.wait_for(asyncio.gather(*loop._active_tasks["cli:test"]), 5)
        session = loop.sessions.get_or_create("cli:test")
        assert process.await_count == 1
        assert permissions[:3] == [False, True, True]
        assert "Discuss the migration" in calls[1]
        assert "execute the agreed plan" in calls[1]
        assert "Goal Runtime Guidance" in calls[1]
        assert "create_goal is unavailable for this turn" in calls[-1]
        assert session.metadata[GOAL_STATE_KEY]["status"] == "completed"
        assert "Verify the migration" in session.metadata[GOAL_STATE_KEY]["objective"]
        assert goal_mutation_allowed() is False
        persisted = SessionManager(tmp_path).get_or_create("cli:test").messages
        visible = public_history_messages([
            row for row in persisted if not is_hidden_history_message(row)
        ])
        assert sum(row.get("content") == command for row in visible) == 1
        hidden = [row for row in persisted if is_hidden_history_message(row)]
        assert len(hidden) == 1
        assert "execute the agreed plan" in hidden[0]["content"]
        assert "preceding conversation" in hidden[0]["content"]
    finally:
        release.set()
        loop.stop()
        await asyncio.wait_for(run, 5)


@pytest.mark.parametrize("overrides", [
    {"content": "/goal"},
    {"content": "please /goal execute"},
    {"channel": "system", "input_role": "user"},
    {"sender_id": "subagent"},
    {"input_role": "system"},
    {"metadata": {"_internal_continuation": True}},
    {"metadata": {"_cron_trigger": {"job_id": "job"}}},
])
async def test_only_explicit_user_goal_can_generate_internal_input(tmp_path, overrides):
    fields = dict(channel="cli", sender_id="user", chat_id="test", content="/goal execute")
    fields.update(overrides)
    msg = InboundMessage(**fields)
    loop = AgentLoop(bus=MessageBus(), provider=MagicMock(), workspace=tmp_path, model="test-model")
    try:
        await loop._dispatch_command_inline(msg, msg.session_key, msg.content, loop.commands.dispatch)
        assert loop._pending_queues == {}
        assert goal_mutation_allowed() is False
        assert loop.sessions.get_or_create(msg.session_key).messages == []
    finally:
        await loop.aclose()


@pytest.mark.parametrize("boundary", ["text", "tool", "error", "empty"])
async def test_goal_at_iteration_limit_stays_queued_for_a_tool_capable_turn(tmp_path, boundary):
    from agent.session_helpers import run_session

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    loop = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        model="test-model", max_iterations=1,
    )
    calls = []
    goal = InboundMessage(
        channel="cli", sender_id="user", chat_id="test", content="/goal verify the migration",
    )

    async def respond(**kwargs):
        calls.append(str(kwargs["messages"]))
        if len(calls) == 1:
            await loop._dispatch_command_inline(
                goal, goal.session_key, goal.content, loop.commands.dispatch,
            )
            if boundary == "tool":
                return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                    id="list", name="list_dir", arguments={"path": "."},
                )])
            if boundary == "error":
                return LLMResponse(content="Temporary model error", finish_reason="error")
            if boundary == "empty":
                return LLMResponse(content="")
            return LLMResponse(content="The migration plan is ready.")
        if kwargs.get("tools") and GOAL_STATE_KEY not in loop.sessions.get_or_create("cli:test").metadata:
            assert goal_mutation_allowed() is True
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="create", name="create_goal",
                arguments={"objective": "Verify the migration."},
            )])
        if kwargs.get("tools"):
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="complete", name="update_goal",
                arguments={"action": "complete", "recap": "Verified."},
            )])
        return LLMResponse(content="done")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    try:
        await run_session(loop, InboundMessage(
            channel="cli", sender_id="user", chat_id="test", content="Discuss the migration.",
        ))
        session = loop.sessions.get_or_create("cli:test")
        assert session.metadata[GOAL_STATE_KEY]["status"] == "completed"
        goal_calls = [call for call in calls if "Goal Runtime Guidance" in call]
        assert goal_calls
        assert "Discuss the migration" in goal_calls[0]
        assert "verify the migration" in goal_calls[0]
        assert goal_mutation_allowed() is False
    finally:
        await loop.aclose()


async def test_generated_goal_input_survives_pending_followup_recovery(tmp_path):
    from agent.session_helpers import run_session
    from nanobot.command.router import CommandContext
    from nanobot.session.recovery import pending_followups, record_pending_followup

    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    message = InboundMessage(
        channel="websocket", sender_id="user", chat_id="test", content="/goal verify the migration",
    )
    try:
        generated = await loop.commands.dispatch(CommandContext(
            msg=message, session=None, key=message.session_key,
            raw=message.content, loop=loop, is_user_turn=True,
        ))
        assert isinstance(generated, InboundMessage)
        session = loop.sessions.get_or_create(message.session_key)
        assert record_pending_followup(session, generated)
        loop.sessions.save(session)
        reloaded = SessionManager(tmp_path).get_or_create(message.session_key)
        recovered, = pending_followups(reloaded)
        assert recovered.content == generated.content
        assert recovered.metadata["goal_requested"] is True
        assert goal_mutation_allowed() is False
        provider.chat_stream_with_retry = AsyncMock(side_effect=[
            LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="create", name="create_goal", arguments={"objective": "Verify the migration."},
            )]),
            LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="complete", name="update_goal", arguments={"action": "complete", "recap": "Verified."},
            )]),
            LLMResponse(content="done"),
        ])
        await run_session(loop, recovered)
        assert session.metadata[GOAL_STATE_KEY]["status"] == "completed"
        assert pending_followups(session) == []
        assert sum(row.get("content") == message.content for row in session.messages) == 1
        assert sum(is_hidden_history_message(row) for row in session.messages) == 1
        assert goal_mutation_allowed() is False
    finally:
        await loop.aclose()
