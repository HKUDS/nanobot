import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.session_helpers import stop_loop
from nanobot.agent.goal_permission import goal_mutation_allowed, goal_mutation_permission
from nanobot.agent.loop import AgentLoop as CoreAgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import GoalStatusEvent, TurnEndEvent
from nanobot.bus.queue import MessageBus
from nanobot.goal.assembly import install_goal
from nanobot.providers.base import (
    GenerationSettings,
    LLMResponse,
    LLMUsage,
    ProviderConversationState,
    ToolCallRequest,
)
from nanobot.runtime_context import public_history_messages
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WebuiTurnCoordinator


def _assembled_loop(*args, **kwargs):
    return CoreAgentLoop(*args, builtin_assembly=install_goal, **kwargs)


@pytest.mark.parametrize("command", [
    "/goal execute the agreed plan",
    "/GOAL@nanobot execute the agreed plan",
    "/goal /tmp/project: execute the agreed plan",
])
async def test_goal_input_enters_running_turn_with_scoped_permission(tmp_path, command):
    task = command.split(" ", 1)[1]
    first_call = asyncio.Event()
    release = asyncio.Event()
    calls = []
    permissions = []
    provider = MagicMock(aclose=AsyncMock())
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
        return LLMResponse(content="done")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = _assembled_loop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
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
            while "cli:test" not in loop._pending_queues or loop._pending_queues["cli:test"].empty():
                await asyncio.sleep(0)
        assert len(calls) == 1
        release.set()
        await asyncio.wait_for(asyncio.gather(*loop._active_tasks["cli:test"]), 5)
        session = (await loop.sessions.state.get("cli:test"))
        assert process.await_count == 1
        assert permissions[:3] == [False, True, True]
        assert "Discuss the migration" in calls[1]
        assert task in calls[1]
        assert "Goal Runtime Guidance" in calls[1]
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
        assert public_history_messages(hidden)[0]["content"] == task
    finally:
        release.set()
        await stop_loop(loop, run, timeout=5)


async def test_scheduled_goal_command_cannot_generate_internal_input(tmp_path):
    msg = InboundMessage(
        channel="cli", sender_id="user", chat_id="test", content="/goal execute",
        metadata={"_cron_trigger": {"job_id": "job"}},
    )
    loop = _assembled_loop(bus=MessageBus(), provider=MagicMock(aclose=AsyncMock()), workspace=tmp_path, model="test-model")
    try:
        await loop._dispatch_command_inline(msg, msg.session_key, msg.content, loop.commands.dispatch)
        response = loop.bus.outbound.get_nowait()
        assert "only be started by a user" in response.content
        assert loop._pending_queues == {}
        assert goal_mutation_allowed() is False
        assert (await loop.sessions.state.get(msg.session_key)).messages == []
    finally:
        await loop.aclose()


@pytest.mark.parametrize("boundary", ["text", "tool", "error", "empty"])
async def test_goal_at_iteration_limit_stays_queued_for_a_tool_capable_turn(tmp_path, boundary):
    from agent.session_helpers import run_session

    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    loop = _assembled_loop(
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
        if kwargs.get("tools") and GOAL_STATE_KEY not in (await loop.sessions.state.get("cli:test")).metadata:
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
        session = (await loop.sessions.state.get("cli:test"))
        assert session.metadata[GOAL_STATE_KEY]["status"] == "completed"
        goal_calls = [call for call in calls if "Goal Runtime Guidance" in call]
        assert goal_calls
        assert "Discuss the migration" in goal_calls[0]
        assert "verify the migration" in goal_calls[0]
        assert goal_mutation_allowed() is False
    finally:
        await loop.aclose()


async def test_generated_goal_input_survives_pending_followup_recovery(tmp_path):
    from nanobot.command.router import CommandContext, CommandExpansion
    from nanobot.session.recovery import pending_followups

    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    loop = _assembled_loop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    message = InboundMessage(
        channel="websocket", sender_id="user", chat_id="test", content="/goal /stop",
    )
    try:
        context = CommandContext(
            msg=message, session=None, key=message.session_key,
            raw=message.content, loop=loop, is_user_turn=True,
        )
        expansion = await loop.commands.dispatch(context)
        assert isinstance(expansion, CommandExpansion)
        generated = await loop._prepare_command_expansion(context, expansion)
        assert isinstance(generated, InboundMessage)
        assert await loop.sessions.state.queue_followup(message.session_key, generated)
    finally:
        await loop.aclose()

    loop = _assembled_loop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    session = (await loop.sessions.state.get(message.session_key))
    recovered, = pending_followups(session)
    responses = iter([
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="create", name="create_goal", arguments={"objective": "Verify the migration."},
        )]),
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="complete", name="update_goal", arguments={"action": "complete", "recap": "Verified."},
        )]),
        LLMResponse(content="done"),
    ])

    async def respond(**kwargs):
        assert any(
            row.get("role") == "user" and row.get("content", "").startswith("/stop")
            for row in kwargs["messages"]
        )
        return next(responses)

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    run = asyncio.create_task(loop.run())
    try:
        assert recovered.content == "/stop"
        assert recovered.metadata["goal_requested"] is True
        assert goal_mutation_allowed() is False
        await loop.bus.publish_inbound(recovered)
        async with asyncio.timeout(5):
            while (await loop.bus.consume_outbound()).content != "done":
                pass
        session = await loop.sessions.state.get(message.session_key)
        assert session.metadata[GOAL_STATE_KEY]["status"] == "completed"
        assert pending_followups(session) == []
        assert sum(row.get("content") == message.content for row in session.messages) == 1
        assert sum(is_hidden_history_message(row) for row in session.messages) == 1
        assert goal_mutation_allowed() is False
    finally:
        loop.stop()
        await asyncio.wait_for(run, 5)


async def test_internal_continuation_cannot_inherit_goal_permission(tmp_path):
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    loop = _assembled_loop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    message = InboundMessage(
        channel="cli", sender_id="automation", chat_id="test", content="Continue working",
        metadata={"goal_requested": True, "_internal_continuation": True},
    )
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="create", name="create_goal", arguments={"objective": "An unauthorized goal."},
        )]),
        LLMResponse(content="done"),
    ])
    try:
        with goal_mutation_permission(True):
            await loop._process_message(message, session_key="cli:test")
            assert goal_mutation_allowed() is True
        assert GOAL_STATE_KEY not in (await loop.sessions.state.get("cli:test")).metadata
        final_request = provider.chat_stream_with_retry.await_args.kwargs["messages"]
        assert "create_goal is unavailable for this turn" in str(final_request)
        assert goal_mutation_allowed() is False
    finally:
        await loop.aclose()


async def test_goal_checkpoint_failure_finishes_visible_run_without_restarting(tmp_path, monkeypatch):
    from agent.session_helpers import run_session

    bus = MessageBus()
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content=None, tool_calls=[ToolCallRequest(
        id="list", name="list_dir", arguments={"path": "."},
    )]))
    loop = _assembled_loop(bus=bus, provider=provider, workspace=tmp_path, model="test-model", max_iterations=1)
    WebuiTurnCoordinator(
        bus=bus, sessions=loop.sessions,
        schedule_background=lambda coro: loop.schedule_background(coro),
    ).subscribe()
    session = await loop.sessions.state.get("websocket:goal-save-fail")
    await loop.sessions.state.update_metadata(session.key, {
        "webui": True, "title": "Goal", "title_user_edited": True,
        GOAL_STATE_KEY: {"status": "active", "objective": "Verify the task."},
    })
    checkpoint_view = loop.sessions.state.checkpoint_view
    checkpoints = 0

    async def fail_checkpoint(session, payload):
        nonlocal checkpoints
        if payload["phase"] == "tools_completed":
            checkpoints += 1
            if checkpoints == 3:
                raise OSError("synthetic checkpoint failure")
        await checkpoint_view(session, payload)

    monkeypatch.setattr(loop.sessions.state, "checkpoint_view", fail_checkpoint)
    loop.runner.run = AsyncMock(wraps=loop.runner.run)
    try:
        await run_session(loop, InboundMessage(
            channel="websocket", sender_id="user", chat_id="goal-save-fail", content="Continue",
            metadata={"webui": True, "webui_turn_id": "save-fail-turn"},
        ))
        events = []
        while not bus.outbound.empty():
            events.append(bus.outbound.get_nowait())
        endings = [m.event for m in events if isinstance(m.event, TurnEndEvent)]
        assert len(endings) == 1 and endings[0].outcome == "failed"
        assert [m.event.status for m in events if isinstance(m.event, GoalStatusEvent)] == ["running", "idle"]
        assert provider.chat_stream_with_retry.await_count == 3
        loop.runner.run.assert_awaited_once()
        assert session.key not in loop._pending_queues
        saved = await loop.sessions.state.read(session.key)
        assert saved.metadata[GOAL_STATE_KEY]["status"] == "active"
    finally:
        await loop.aclose()


async def test_active_goal_keeps_candidate_history_until_successful_closure(tmp_path):
    from agent.session_helpers import run_session

    bus = MessageBus()
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    provider.can_resume_conversation_state.return_value = True
    state = ProviderConversationState(
        kind="openai_responses", provider="openai:test", model="test-model", version=1,
        payload={"items": [{"type": "reasoning", "encrypted_content": "private-goal-state"}]},
    )
    usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15, reported_tokens=15)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def respond(**kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            resumed = kwargs["provider_context"].conversation_state
            assert resumed is not None and resumed.payload == state.payload
            assert any(row.get("content") == "Evidence 1 recorded." for row in kwargs["messages"])
            if len(calls) <= 16:
                assert any("Please continue working toward the objective" in str(row.get("content"))
                           for row in resumed.pending_messages)
            else:
                assert any(row.get("tool_call_id") == "close" for row in resumed.pending_messages)
        if len(calls) <= 15:
            assert kwargs.get("tools")
            return LLMResponse(content=f"Evidence {len(calls)} recorded.", usage=usage, provider_state=state)
        if len(calls) == 16:
            assert kwargs.get("tools")
            entered.set()
            await release.wait()
            return LLMResponse(content=None, usage=usage, provider_state=state, tool_calls=[ToolCallRequest(
                id="close", name="update_goal", arguments={"action": "complete", "recap": "Evidence reviewed."},
            )])
        assert len(calls) == 17 and not kwargs.get("tools")
        return LLMResponse(content="Evidence reviewed.", usage=usage, provider_state=state)

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    loop = _assembled_loop(bus=bus, provider=provider, workspace=tmp_path,
                           model="test-model", max_iterations=1)
    loop.runner.run = AsyncMock(wraps=loop.runner.run)
    loop._process_message = AsyncMock(wraps=loop._process_message)
    WebuiTurnCoordinator(
        bus=bus, sessions=loop.sessions,
        schedule_background=lambda coro: loop.schedule_background(coro),
    ).subscribe()
    session = await loop.sessions.state.get("websocket:goal-limit")
    await loop.sessions.state.update_metadata(session.key, {
        GOAL_STATE_KEY: {"status": "active", "objective": "Keep investigating."},
        "webui": True, "title": "Goal", "title_user_edited": True,
    })
    run = asyncio.create_task(run_session(loop, InboundMessage(
        channel="websocket", sender_id="user", chat_id="goal-limit", content="/goal Keep investigating.",
        metadata={"webui": True, "webui_turn_id": "goal-turn"},
    )))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        events = []
        while not bus.outbound.empty():
            events.append(bus.outbound.get_nowait())
        assert [m.event.status for m in events if isinstance(m.event, GoalStatusEvent)] == ["running"]
        assert not any(isinstance(m.event, TurnEndEvent) for m in events)
        release.set()
        await asyncio.wait_for(run, 5)
        while not bus.outbound.empty():
            events.append(bus.outbound.get_nowait())
        statuses = [m.event for m in events if isinstance(m.event, GoalStatusEvent)]
        assert [event.status for event in statuses] == ["running", "idle"]
        assert statuses[0].started_at is not None
        endings = [m.event for m in events if isinstance(m.event, TurnEndEvent)]
        assert len(endings) == 1 and endings[0].outcome == "completed"
        assert isinstance(endings[0].latency_ms, int)
        assert endings[0].usage is not None and endings[0].usage.total_tokens == 255
        assert len(endings[0].round_usages) == 17
        assert len(calls) == 17
        loop.runner.run.assert_awaited_once()
        loop._process_message.assert_awaited_once()
        saved = await loop.sessions.state.read(session.key)
        assert saved.metadata[GOAL_STATE_KEY]["status"] == "completed"
        assert saved.provider_state is not None and saved.provider_state.payload == state.payload
        visible = public_history_messages([row for row in saved.messages if not is_hidden_history_message(row)])
        assert [row["content"] for row in visible if row["role"] == "user"] == ["/goal Keep investigating."]
        for number in range(1, 16):
            assert sum(row.get("content") == f"Evidence {number} recorded." for row in visible) == 1
        assert sum(row.get("content") == "Evidence reviewed." for row in visible) == 1
        assert visible[-1]["content"] == "Evidence reviewed."
        assert [row["tool_call_id"] for row in saved.messages if row["role"] == "tool"] == ["close"]
        assert sum(row.get("_hidden_history") == {"kind": "internal_continuation"} for row in saved.messages) == 15
        assert "private-goal-state" not in str(visible)
        assert session.key not in loop._pending_queues
    finally:
        release.set()
        if not run.done():
            await loop._cancel_active_tasks(session.key)
        await asyncio.gather(run, return_exceptions=True)
        await loop.aclose()


async def test_replaced_goal_uses_current_objective_for_same_run_prompt(tmp_path):
    from agent.session_helpers import run_session

    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    loop = _assembled_loop(bus=MessageBus(), provider=provider, workspace=tmp_path,
                           model="test-model", max_iterations=1)
    session = await loop.sessions.state.get("cli:replacement")
    await loop.sessions.state.update_metadata(session.key, {
        GOAL_STATE_KEY: {"status": "active", "objective": "Old objective."},
    })
    calls = []
    replacement = InboundMessage(
        channel="cli", sender_id="user", chat_id="replacement", content="/goal New objective.",
    )

    async def respond(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            await loop._dispatch_command_inline(
                replacement, replacement.session_key, replacement.content, loop.commands.dispatch,
            )
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="list", name="list_dir", arguments={"path": "."},
            )])
        if len(calls) == 2:
            assert goal_mutation_allowed()
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="replace", name="update_goal", arguments={"action": "replace", "objective": "New objective."},
            )])
        if len(calls) == 3:
            return LLMResponse(content="The replacement objective needs one more check.")
        if len(calls) == 4:
            prompts = [
                message["content"] for message in kwargs["messages"]
                if is_hidden_history_message(message) and message.get("role") == "user"
            ]
            assert prompts and "New objective." in prompts[-1] and "Old objective." not in prompts[-1]
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id="complete", name="update_goal", arguments={"action": "complete", "recap": "Done."},
            )])
        return LLMResponse(content="Done.")

    provider.chat_stream_with_retry = AsyncMock(side_effect=respond)
    try:
        await run_session(loop, InboundMessage(
            channel="cli", sender_id="user", chat_id="replacement", content="Continue the old objective.",
        ))
        assert len(calls) == 5
        saved = await loop.sessions.state.read(session.key)
        assert saved.metadata[GOAL_STATE_KEY]["objective"] == "New objective."
        assert saved.metadata[GOAL_STATE_KEY]["status"] == "completed"
        visible = public_history_messages([row for row in saved.messages if not is_hidden_history_message(row)])
        assert sum(row.get("content") == replacement.content for row in visible) == 1
    finally:
        await loop.aclose()


async def test_failed_goal_completion_keeps_running_until_a_successful_block(tmp_path, monkeypatch):
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens.return_value = (100, "test")
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="complete", name="update_goal", arguments={"action": "complete", "recap": "Done."},
        )]),
        LLMResponse(content="The task is done."),
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="block", name="update_goal", arguments={"action": "block", "recap": "Save failed."},
        )]),
        LLMResponse(content="The goal is blocked."),
    ])
    loop = _assembled_loop(bus=MessageBus(), provider=provider, workspace=tmp_path,
                           model="test-model", max_iterations=4)
    session = await loop.sessions.state.get("cli:failed-goal-update")
    await loop.sessions.state.update_metadata(session.key, {
        GOAL_STATE_KEY: {"status": "active", "objective": "Verify the task."},
    })
    replace_metadata = loop.sessions._store.replace_metadata

    def fail_completion(key, metadata, **kwargs):
        if metadata.get(GOAL_STATE_KEY, {}).get("status") == "completed":
            raise OSError("synthetic goal commit failure")
        return replace_metadata(key, metadata, **kwargs)

    monkeypatch.setattr(loop.sessions._store, "replace_metadata", fail_completion)
    try:
        result = await loop.process_direct("Continue", session_key=session.key)
        assert result.content == "The goal is blocked."
        assert provider.chat_stream_with_retry.await_count == 4
        calls = provider.chat_stream_with_retry.await_args_list
        assert "synthetic goal commit failure" in str(calls[1].kwargs["messages"])
        assert "Please continue working toward the objective" in str(calls[2].kwargs["messages"])
        saved = await loop.sessions.state.read(session.key)
        assert saved.metadata[GOAL_STATE_KEY]["status"] == "blocked"
    finally:
        await loop.aclose()


@pytest.mark.parametrize("operation", ["reset", "delete"])
async def test_queued_goal_command_does_not_write_to_an_obsolete_generation(tmp_path, operation):
    from nanobot.session.sqlite_store import SessionConflictError

    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings()
    loop = _assembled_loop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    key = "websocket:old-goal-command"
    session = await loop.sessions.state.get(key)
    message = InboundMessage(
        channel="websocket", sender_id="user", chat_id="old-goal-command", content="/goal Old task",
        session_generation=session.generation, require_existing_session=True,
    )
    try:
        if operation == "reset":
            await loop.sessions.state.reset(key)
        else:
            assert await loop.sessions.state.delete(key)
        with pytest.raises(SessionConflictError):
            await loop._dispatch_command_inline(message, key, message.content, loop.commands.dispatch)
        current = await loop.sessions.state.read(key)
        if operation == "delete":
            assert current is None
        else:
            assert current is not None and current.generation != session.generation
            assert current.messages == []
        assert key not in loop._pending_queues
    finally:
        await loop.aclose()
