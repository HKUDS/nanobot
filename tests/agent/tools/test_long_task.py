from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.goal_permission import goal_mutation_allowed, goal_mutation_permission
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import (
    RequestContext,
    current_request_context,
    request_context,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.outbound_events import GoalStateSyncEvent
from nanobot.bus.queue import MessageBus
from nanobot.goal.assembly import install_goal
from nanobot.goal.runtime import GoalExecutionPolicy
from nanobot.goal.tools import CreateGoalTool, UpdateGoalTool
from nanobot.session.goal_state import GOAL_STATE_KEY, MAX_GOAL_OBJECTIVE_CHARS
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import WebuiTurnCoordinator


def _goal_metadata() -> dict[str, object]:
    return {
        "original_command": "/goal",
        "original_content": "/goal implement the agreed plan",
        "goal_requested": True,
    }


def _request_context(
    *,
    chat_id: str = "c1",
    metadata: dict[str, object] | None = None,
    original_user_text: str | None = "/goal implement the agreed plan",
    channel: str = "websocket",
) -> RequestContext:
    return RequestContext(
        channel=channel,
        chat_id=chat_id,
        session_key=f"{channel}:{chat_id}",
        original_user_text=original_user_text,
        metadata=metadata if metadata is not None else _goal_metadata(),
    )


def _tools(
    sm: SessionManager,
    *,
    metadata: dict[str, object] | None = None,
) -> tuple[CreateGoalTool, UpdateGoalTool, RequestContext]:
    create = CreateGoalTool(sessions=sm)
    update = UpdateGoalTool(sessions=sm)
    rc = _request_context(metadata=metadata)
    return create, update, rc


async def _bound_context(sm: SessionManager, ctx: RequestContext) -> RequestContext:
    if ctx.session_generation is not None or ctx.session_key is None:
        return ctx
    session = await sm.state.get_header(ctx.session_key)
    return replace(ctx, session_generation=session.generation)


async def _execute(tool, ctx: RequestContext, *, allowed: bool = True, **kwargs):
    ctx = await _bound_context(tool._sessions, ctx)
    with request_context(ctx), goal_mutation_permission(allowed):
        return await tool.execute(**kwargs)


@pytest.mark.asyncio
async def test_create_goal_records_goal_metadata(tmp_path):
    sm = SessionManager(tmp_path)
    create, _update, ctx = _tools(sm)
    await sm.state.get("websocket:c1")

    out = await _execute(
        create,
        ctx,
        objective="Do the thing",
        ui_summary="thing",
    )
    assert "Goal recorded" in out

    sess = sm.get_or_create("websocket:c1")
    blob = sess.metadata.get(GOAL_STATE_KEY)
    assert isinstance(blob, dict)
    assert blob["status"] == "active"
    assert blob["objective"] == "Do the thing"
    assert blob["ui_summary"] == "thing"
    assert SessionManager(tmp_path).get_or_create(sess.key).metadata[GOAL_STATE_KEY] == blob
    with GoalExecutionPolicy(sm.state).scope(sess.key, sess.generation, persistent=True) as scope:
        assert "Do the thing" in await scope.continuation_prompt()


@pytest.mark.asyncio
async def test_goal_context_and_mutations_only_read_session_metadata(tmp_path, monkeypatch):
    sm = SessionManager(tmp_path)
    stored = sm.get_or_create("websocket:c1")
    stored.add_message("user", "Keep the previous conversation.")
    stored.add_message("assistant", "Previous answer.")
    sm.save(stored)
    create, update, ctx = _tools(sm)

    def history_unavailable(*_args, **_kwargs):
        pytest.fail("goal metadata operations must not request conversation history")

    monkeypatch.setattr(sm.state, "get", history_unavailable)
    monkeypatch.setattr(sm.state, "read", history_unavailable)
    ordinary = _request_context(metadata={}, original_user_text="Continue.")
    try:
        assert await create.runtime_context_provider()(ordinary) is None
        assert "Goal recorded" in await _execute(create, ctx, objective="Preserve history")
        context = await create.runtime_context_provider()(ordinary)
        assert context is not None and "Preserve history" in context.content
        assert "marked complete" in await _execute(update, ordinary, action="complete")
        assert await create.runtime_context_provider()(ordinary) is None

        reopened = SessionManager(tmp_path).get_or_create(stored.key)
        assert reopened.messages == stored.messages
        assert reopened.metadata[GOAL_STATE_KEY]["status"] == "completed"
    finally:
        await sm.state.aclose()


@pytest.mark.asyncio
async def test_create_goal_rejects_without_explicit_goal_permission(tmp_path):
    sm = SessionManager(tmp_path)
    create, _update, ctx = _tools(sm)
    sess = sm.get_or_create("websocket:c1")
    sess.add_message("user", "/goal implement the old plan")
    sess.add_message("assistant", "The old goal is complete.")
    sess.add_message("user", "Handle this as an ordinary one-time task.")

    out = await _execute(
        create,
        ctx,
        allowed=False,
        objective="Implement another plan.",
    )

    assert "create_goal is unavailable for this turn" in str(out)
    assert "/goal <task>" in str(out)
    assert GOAL_STATE_KEY not in sess.metadata


@pytest.mark.asyncio
async def test_update_goal_complete_closes_active_goal(tmp_path):
    sm = SessionManager(tmp_path)
    create, update, ctx = _tools(sm)

    ctx = await _bound_context(sm, ctx)
    with request_context(ctx), goal_mutation_permission(True):
        await create.execute(objective="X")
        out = await update.execute(action="complete", recap="Done.")
        denied = await create.execute(objective="Another")
        assert goal_mutation_allowed() is False

    assert "marked complete" in out
    assert "create_goal is unavailable for this turn" in str(denied)

    sess = sm.get_or_create("websocket:c1")
    blob = sess.metadata.get(GOAL_STATE_KEY)
    assert blob["status"] == "completed"
    assert blob["recap"] == "Done."


@pytest.mark.asyncio
async def test_update_goal_replace_keeps_goal_active_with_new_objective(tmp_path):
    sm = SessionManager(tmp_path)
    create, update, ctx = _tools(sm)

    await _execute(create, ctx, objective="Old")
    out = await _execute(
        update,
        _request_context(),
        action="replace",
        objective="New",
        ui_summary="new",
    )

    assert "Goal replaced" in out
    blob = sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]
    assert blob["status"] == "active"
    assert blob["objective"] == "New"
    assert blob["previous_objective"] == "Old"
    assert blob["ui_summary"] == "new"
    sess = sm.get_or_create("websocket:c1")
    assert SessionManager(tmp_path).get_or_create(sess.key).metadata[GOAL_STATE_KEY] == blob
    with GoalExecutionPolicy(sm.state).scope(sess.key, sess.generation, persistent=True) as scope:
        assert "New" in await scope.continuation_prompt()


@pytest.mark.asyncio
async def test_goal_state_mutations_roll_back_on_save_failure(tmp_path, monkeypatch):
    sm = SessionManager(tmp_path)
    create, update, _context = _tools(sm)
    sess = sm.get_or_create("websocket:c1")
    sess.metadata["marker"] = {"keep": True}
    sm.save(sess)
    original_save = sm._store.replace_metadata
    create_context = _request_context()

    def fail_save(*_args, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(sm._store, "replace_metadata", fail_save)
    with pytest.raises(OSError, match="disk unavailable"):
        await _execute(create, create_context, objective="Old")

    assert sess.metadata == {"marker": {"keep": True}}
    assert GOAL_STATE_KEY not in SessionManager(tmp_path).get_or_create("websocket:c1").metadata

    monkeypatch.setattr(sm._store, "replace_metadata", original_save)
    assert "Goal recorded" in await _execute(create, create_context, objective="Old")
    sess = sm.get_or_create("websocket:c1")
    replace_context = _request_context()

    monkeypatch.setattr(sm._store, "replace_metadata", fail_save)
    with pytest.raises(OSError, match="disk unavailable"):
        await _execute(update, replace_context, action="replace", objective="New")

    assert sess.metadata[GOAL_STATE_KEY]["objective"] == "Old"
    assert sess.metadata["marker"] == {"keep": True}
    persisted = SessionManager(tmp_path).get_or_create("websocket:c1").metadata
    assert persisted[GOAL_STATE_KEY]["objective"] == "Old"
    assert persisted["marker"] == {"keep": True}

    monkeypatch.setattr(sm._store, "replace_metadata", original_save)
    assert "Goal replaced" in await _execute(
        update,
        replace_context,
        action="replace",
        objective="New",
    )
    sess = sm.get_or_create("websocket:c1")
    assert sess.metadata["marker"] == {"keep": True}
    assert (
        SessionManager(tmp_path).get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]["objective"]
        == "New"
    )


@pytest.mark.asyncio
async def test_goal_tools_reject_oversized_objectives(tmp_path):
    sm = SessionManager(tmp_path)
    create = CreateGoalTool(sessions=sm)
    create_context = _request_context()
    oversized = "x" * (MAX_GOAL_OBJECTIVE_CHARS + 1)

    create_out = await _execute(create, create_context, objective=oversized)

    assert f"must not exceed {MAX_GOAL_OBJECTIVE_CHARS}" in str(create_out)
    assert GOAL_STATE_KEY not in sm.get_or_create("websocket:c1").metadata
    assert "Goal recorded" in await _execute(
        create,
        create_context,
        objective="x" * MAX_GOAL_OBJECTIVE_CHARS,
    )

    update = UpdateGoalTool(sessions=sm)
    replace_context = _request_context()
    replace_out = await _execute(update, replace_context, action="replace", objective=oversized)

    assert f"must not exceed {MAX_GOAL_OBJECTIVE_CHARS}" in str(replace_out)
    assert len(sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]["objective"]) == (
        MAX_GOAL_OBJECTIVE_CHARS
    )


@pytest.mark.asyncio
async def test_active_goal_create_failure_preserves_permission_for_replace(tmp_path):
    sm = SessionManager(tmp_path)
    create, update, initial_context = _tools(sm)
    assert "Goal recorded" in await _execute(create, initial_context, objective="Old")

    replacement_context = await _bound_context(sm, _request_context())
    with request_context(replacement_context), goal_mutation_permission(True):
        create_out = await create.execute(objective="New")
        assert goal_mutation_allowed() is True
        replace_out = await update.execute(action="replace", objective="New")
        assert goal_mutation_allowed() is True

    assert "already active" in str(create_out)
    assert "Goal replaced" in replace_out


@pytest.mark.asyncio
async def test_update_goal_replace_requires_explicit_goal_permission(tmp_path):
    sm = SessionManager(tmp_path)
    create, update, initial_context = _tools(sm)
    assert "Goal recorded" in await _execute(create, initial_context, objective="Old")
    ordinary_context = _request_context(original_user_text="Continue the existing objective.")

    unauthorized = await _execute(
        update,
        ordinary_context,
        allowed=False,
        action="replace",
        objective="Unrequested",
    )

    assert "replacing the goal is unavailable for this turn" in str(unauthorized)
    assert "/goal <task>" in str(unauthorized)
    assert sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]["objective"] == "Old"
    replace_context = await _bound_context(sm, _request_context())

    with request_context(replace_context), goal_mutation_permission(True):
        assert "Goal replaced" in await update.execute(action="replace", objective="New")
        reused = await update.execute(action="replace", objective="Another")
        assert goal_mutation_allowed() is True

    assert "Goal replaced" in reused
    assert sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]["objective"] == "Another"


@pytest.mark.asyncio
async def test_goal_tools_keep_request_context_per_task(tmp_path):
    sm = SessionManager(tmp_path)
    create = CreateGoalTool(sessions=sm)
    update = UpdateGoalTool(sessions=sm)
    ctx_a = RequestContext(
        channel="websocket",
        chat_id="a",
        session_key="websocket:a",
        metadata=_goal_metadata(),
    )
    ctx_b = RequestContext(
        channel="websocket",
        chat_id="b",
        session_key="websocket:b",
        metadata=_goal_metadata(),
    )

    ctx_a = await _bound_context(sm, ctx_a)
    ctx_b = await _bound_context(sm, ctx_b)
    task_a = asyncio.create_task(_execute(create, ctx_a, objective="Goal A"))
    task_b = asyncio.create_task(_execute(create, ctx_b, objective="Goal B"))
    await asyncio.gather(task_a, task_b)

    assert sm.get_or_create("websocket:a").metadata[GOAL_STATE_KEY]["objective"] == "Goal A"
    assert sm.get_or_create("websocket:b").metadata[GOAL_STATE_KEY]["objective"] == "Goal B"

    a_revoked = asyncio.Event()

    async def complete_a() -> None:
        with request_context(ctx_a), goal_mutation_permission(True):
            await update.execute(action="complete", recap="Done A")
            assert goal_mutation_allowed() is False
            a_revoked.set()

    async def replace_b() -> None:
        with request_context(ctx_b), goal_mutation_permission(True):
            await a_revoked.wait()
            assert goal_mutation_allowed() is True
            await update.execute(action="replace", objective="Goal B2")

    await asyncio.gather(complete_a(), replace_b())

    assert sm.get_or_create("websocket:a").metadata[GOAL_STATE_KEY]["recap"] == "Done A"
    assert sm.get_or_create("websocket:b").metadata[GOAL_STATE_KEY]["objective"] == "Goal B2"


@pytest.mark.asyncio
async def test_registry_does_not_reuse_goal_context_after_request_scope(tmp_path):
    sm = SessionManager(tmp_path)
    create = CreateGoalTool(sessions=sm)
    update = UpdateGoalTool(sessions=sm)
    registry = ToolRegistry()
    registry.register(create)
    registry.register(update)
    sess = sm.get_or_create("websocket:c1")
    sess.metadata[GOAL_STATE_KEY] = {"status": "active", "objective": "Old"}
    sm.save(sess)
    ctx = await _bound_context(sm, _request_context())

    with request_context(ctx), goal_mutation_permission(True):
        create_out = await registry.execute("create_goal", {"objective": "New"})
        complete_out = await registry.execute(
            "update_goal",
            {"action": "complete", "recap": "Old goal done."},
        )
        denied_out = await registry.execute("create_goal", {"objective": "Denied"})
        assert goal_mutation_allowed() is False

    assert "already active" in str(create_out)
    assert "marked complete" in str(complete_out)
    assert "create_goal is unavailable for this turn" in str(denied_out)
    assert current_request_context() is None

    leaked_out = await registry.execute("create_goal", {"objective": "Leaked"})

    assert "missing routing context" in str(leaked_out)
    assert sm.get_or_create(sess.key).metadata[GOAL_STATE_KEY]["status"] == "completed"


@pytest.mark.asyncio
async def test_goal_state_events_publish_active_then_inactive(tmp_path):
    bus = MessageBus()
    bus.publish_outbound = AsyncMock()
    sm = SessionManager(tmp_path)
    WebuiTurnCoordinator(
        bus=bus,
        sessions=sm,
        schedule_background=lambda _coro: None,
    ).subscribe()
    create = CreateGoalTool(sessions=sm, bus=bus)
    update = UpdateGoalTool(sessions=sm, bus=bus)
    rc = _request_context(chat_id="chat-99")
    await _execute(
        create,
        rc,
        objective="Objective alpha",
        ui_summary="alpha",
    )

    bus.publish_outbound.assert_awaited_once()
    call = bus.publish_outbound.await_args.args[0]
    assert call.channel == "websocket"
    assert call.chat_id == "chat-99"
    assert isinstance(call.event, GoalStateSyncEvent)
    assert call.event.goal_state == {
        "active": True,
        "status": "active",
        "ui_summary": "alpha",
        "objective": "Objective alpha",
    }

    bus.publish_outbound.reset_mock()
    await _execute(
        update,
        RequestContext(
            channel="websocket",
            chat_id="chat-99",
            session_key="websocket:chat-99",
        ),
        action="complete",
        recap="Done.",
    )

    bus.publish_outbound.assert_awaited_once()
    call = bus.publish_outbound.await_args.args[0]
    assert isinstance(call.event, GoalStateSyncEvent)
    assert call.event.goal_state == {"active": False}


@pytest.mark.asyncio
async def test_update_goal_without_active_is_noop_message(tmp_path):
    sm = SessionManager(tmp_path)
    _create, update, ctx = _tools(sm)

    out = await _execute(update, ctx, action="complete", recap="n/a")
    assert "No active" in out


@pytest.mark.asyncio
async def test_goal_tools_registered_by_builtin_assembly(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model",
                     builtin_assembly=install_goal)

    create = loop.tools.get("create_goal")
    update = loop.tools.get("update_goal")
    assert create is not None and create.name == "create_goal"
    assert update is not None and update.name == "update_goal"
    assert set(create.parameters["properties"]) == {"objective", "ui_summary"}
    assert create.parameters["required"] == ["objective"]
    assert (
        create.parameters["properties"]["objective"]["maxLength"]
        == MAX_GOAL_OBJECTIVE_CHARS
    )
    assert (
        update.parameters["properties"]["objective"]["maxLength"]
        == MAX_GOAL_OBJECTIVE_CHARS
    )
    model_visible_contract = " ".join(
        (
            create.description,
            str(create.parameters),
            update.description,
            str(update.parameters),
        )
    ).lower()
    assert "authoriz" not in model_visible_contract
    assert "/goal" not in model_visible_contract


@pytest.mark.parametrize("caller_supplied", [False, True])
async def test_goal_assembly_preserves_builtin_plugin_precedence(tmp_path, monkeypatch, caller_supplied):
    from nanobot.agent.tools.loader import ToolLoader

    class ConflictingTool(Tool):
        @property
        def name(self):
            return "create_goal"

        @property
        def description(self):
            return "Synthetic conflicting tool"

        @property
        def parameters(self):
            return {"type": "object", "properties": {}}

        async def execute(self, **kwargs):
            return "external"

    monkeypatch.setattr(ToolLoader, "_discover_plugins", lambda _self: {"external": ConflictingTool})
    registry = ToolRegistry()
    supplied = ConflictingTool()
    if caller_supplied:
        registry.register(supplied)
    provider = MagicMock(aclose=AsyncMock())
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model",
                     tool_registry=registry, builtin_assembly=install_goal)
    try:
        if caller_supplied:
            assert loop.tools.get("create_goal") is supplied
        else:
            assert isinstance(loop.tools.get("create_goal"), CreateGoalTool)
    finally:
        await loop.aclose()
