"""Tests for sustained goal tools (``create_goal``, ``update_goal``)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.goal_permission import goal_mutation_allowed, goal_mutation_permission
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import (
    RequestContext,
    current_request_context,
    request_context,
)
from nanobot.agent.tools.long_task import (
    CreateGoalTool,
    UpdateGoalTool,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.outbound_events import GoalStateSyncEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventBus
from nanobot.session.goal_state import GOAL_STATE_KEY, MAX_GOAL_OBJECTIVE_CHARS
from nanobot.session.manager import SessionManager
from nanobot.session.turn_continuation import should_finalize_on_max_iterations
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


async def _execute(tool, ctx: RequestContext, *, allowed: bool = True, **kwargs):
    with request_context(ctx), goal_mutation_permission(allowed):
        return await tool.execute(**kwargs)


@pytest.mark.asyncio
async def test_create_goal_records_goal_metadata(tmp_path):
    sm = SessionManager(tmp_path)
    create, _update, ctx = _tools(sm)
    sm.get_or_create("websocket:c1").metadata["_sustained_goal_continuation_rounds"] = 12

    out = await _execute(
        create,
        ctx,
        objective="Do the thing",
        completion_evidence="the thing is done and verified",
        ui_summary="thing",
    )
    assert "Goal recorded" in out

    sess = sm.get_or_create("websocket:c1")
    blob = sess.metadata.get(GOAL_STATE_KEY)
    assert isinstance(blob, dict)
    assert blob["status"] == "active"
    assert blob["objective"] == "Do the thing"
    assert blob["ui_summary"] == "thing"
    assert "_sustained_goal_continuation_rounds" not in sess.metadata
    assert "_sustained_goal_continuation_rounds" not in (
        SessionManager(tmp_path).get_or_create("websocket:c1").metadata
    )
    assert not should_finalize_on_max_iterations(
        pending_queue_available=True,
        session_metadata=sess.metadata,
    )


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

    with request_context(ctx), goal_mutation_permission(True):
        await create.execute(objective="X", completion_evidence="X is verified done")
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

    await _execute(create, ctx, objective="Old", completion_evidence="old artifact exists")
    sess = sm.get_or_create("websocket:c1")
    sess.metadata["_sustained_goal_continuation_rounds"] = 12
    sm.save(sess)
    out = await _execute(
        update,
        _request_context(),
        action="replace",
        objective="New",
        completion_evidence="new artifact exists",
        ui_summary="new",
    )

    assert "Goal replaced" in out
    blob = sm.get_or_create("websocket:c1").metadata[GOAL_STATE_KEY]
    assert blob["status"] == "active"
    assert blob["objective"] == "New"
    assert blob["previous_objective"] == "Old"
    assert blob["ui_summary"] == "new"
    assert "_sustained_goal_continuation_rounds" not in sess.metadata
    assert "_sustained_goal_continuation_rounds" not in (
        SessionManager(tmp_path).get_or_create("websocket:c1").metadata
    )
    assert not should_finalize_on_max_iterations(
        pending_queue_available=True,
        session_metadata=sess.metadata,
    )


@pytest.mark.asyncio
async def test_goal_state_mutations_roll_back_on_save_failure(tmp_path, monkeypatch):
    sm = SessionManager(tmp_path)
    create, update, _context = _tools(sm)
    sess = sm.get_or_create("websocket:c1")
    sess.metadata["marker"] = {"keep": True}
    sess.metadata["_sustained_goal_continuation_rounds"] = 12
    original_save = sm.save
    create_context = _request_context()

    def fail_save(_session, **_kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(sm, "save", fail_save)
    with pytest.raises(OSError, match="disk unavailable"):
        await _execute(create, create_context, objective="Old", completion_evidence="old artifact exists")

    assert sess.metadata == {
        "marker": {"keep": True},
        "_sustained_goal_continuation_rounds": 12,
    }
    assert GOAL_STATE_KEY not in SessionManager(tmp_path).get_or_create("websocket:c1").metadata

    monkeypatch.setattr(sm, "save", original_save)
    assert "Goal recorded" in await _execute(
        create, create_context, objective="Old", completion_evidence="old artifact exists"
    )
    sess.metadata["_sustained_goal_continuation_rounds"] = 12
    sm.save(sess)
    replace_context = _request_context()

    monkeypatch.setattr(sm, "save", fail_save)
    with pytest.raises(OSError, match="disk unavailable"):
        await _execute(
            update,
            replace_context,
            action="replace",
            objective="New",
            completion_evidence="new artifact exists",
        )

    assert sess.metadata[GOAL_STATE_KEY]["objective"] == "Old"
    assert sess.metadata["_sustained_goal_continuation_rounds"] == 12
    persisted = SessionManager(tmp_path).get_or_create("websocket:c1").metadata
    assert persisted[GOAL_STATE_KEY]["objective"] == "Old"
    assert persisted["_sustained_goal_continuation_rounds"] == 12

    monkeypatch.setattr(sm, "save", original_save)
    assert "Goal replaced" in await _execute(
        update,
        replace_context,
        action="replace",
        objective="New",
        completion_evidence="new artifact exists",
    )
    assert "_sustained_goal_continuation_rounds" not in sess.metadata
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
        completion_evidence="max-size objective is done",
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
    assert "Goal recorded" in await _execute(
        create, initial_context, objective="Old", completion_evidence="old artifact exists"
    )

    replacement_context = _request_context()
    with request_context(replacement_context), goal_mutation_permission(True):
        create_out = await create.execute(objective="New")
        assert goal_mutation_allowed() is True
        replace_out = await update.execute(
            action="replace", objective="New", completion_evidence="new artifact exists"
        )
        assert goal_mutation_allowed() is True

    assert "already active" in str(create_out)
    assert "Goal replaced" in replace_out


@pytest.mark.asyncio
async def test_update_goal_replace_requires_explicit_goal_permission(tmp_path):
    sm = SessionManager(tmp_path)
    create, update, initial_context = _tools(sm)
    assert "Goal recorded" in await _execute(
        create, initial_context, objective="Old", completion_evidence="old artifact exists"
    )
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
    replace_context = _request_context()

    with request_context(replace_context), goal_mutation_permission(True):
        assert "Goal replaced" in await update.execute(
            action="replace", objective="New", completion_evidence="new artifact exists"
        )
        reused = await update.execute(
            action="replace", objective="Another", completion_evidence="other artifact exists"
        )
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

    task_a = asyncio.create_task(
        _execute(create, ctx_a, objective="Goal A", completion_evidence="A done")
    )
    task_b = asyncio.create_task(
        _execute(create, ctx_b, objective="Goal B", completion_evidence="B done")
    )
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
            await update.execute(
                action="replace", objective="Goal B2", completion_evidence="B2 done"
            )

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
    ctx = _request_context()

    with request_context(ctx), goal_mutation_permission(True):
        create_out = await registry.execute(
            "create_goal", {"objective": "New", "completion_evidence": "new artifact exists"}
        )
        complete_out = await registry.execute(
            "update_goal",
            {"action": "complete", "recap": "Old goal done."},
        )
        denied_out = await registry.execute(
            "create_goal", {"objective": "Denied", "completion_evidence": "denied artifact"}
        )
        assert goal_mutation_allowed() is False

    assert "already active" in str(create_out)
    assert "marked complete" in str(complete_out)
    assert "create_goal is unavailable for this turn" in str(denied_out)
    assert current_request_context() is None

    leaked_out = await registry.execute(
        "create_goal", {"objective": "Leaked", "completion_evidence": "leaked artifact"}
    )

    assert "missing routing context" in str(leaked_out)
    assert sess.metadata[GOAL_STATE_KEY]["status"] == "completed"


@pytest.mark.asyncio
async def test_goal_state_events_publish_active_then_inactive(tmp_path):
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    runtime_events = RuntimeEventBus()
    sm = SessionManager(tmp_path)
    WebuiTurnCoordinator(
        bus=bus,
        sessions=sm,
        schedule_background=lambda _coro: None,
    ).subscribe(runtime_events)
    create = CreateGoalTool(sessions=sm, runtime_events=runtime_events)
    update = UpdateGoalTool(sessions=sm, runtime_events=runtime_events)
    rc = _request_context(chat_id="chat-99")
    await _execute(
        create,
        rc,
        objective="Objective alpha",
        completion_evidence="alpha artifact exists",
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
async def test_goal_tools_registered_in_base_registry(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")

    create = loop.tools.get("create_goal")
    update = loop.tools.get("update_goal")
    assert create is not None and create.name == "create_goal"
    assert update is not None and update.name == "update_goal"
    assert set(create.parameters["properties"]) == {
        "objective",
        "completion_evidence",
        "ui_summary",
    }
    assert create.parameters["required"] == ["objective", "completion_evidence"]
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


@pytest.mark.asyncio
async def test_create_goal_requires_completion_evidence(tmp_path):
    sm = SessionManager(tmp_path)
    create, _update, ctx = _tools(sm)

    out = await _execute(create, ctx, objective="Do the thing")

    assert "completion_evidence" in str(out)
    assert GOAL_STATE_KEY not in sm.get_or_create("websocket:c1").metadata


@pytest.mark.asyncio
async def test_create_goal_stores_completion_evidence(tmp_path):
    from nanobot.session.goal_state import goal_state_runtime_lines

    sm = SessionManager(tmp_path)
    create, _update, ctx = _tools(sm)

    out = await _execute(
        create,
        ctx,
        objective="Write the plan file",
        completion_evidence="plan.md exists and covers 14 days",
    )

    assert "Goal recorded" in str(out)
    meta = sm.get_or_create("websocket:c1").metadata
    assert meta[GOAL_STATE_KEY]["completion_evidence"] == "plan.md exists and covers 14 days"
    assert any("Done when: plan.md exists" in line for line in goal_state_runtime_lines(meta))


@pytest.mark.asyncio
async def test_replace_requires_completion_evidence(tmp_path):
    sm = SessionManager(tmp_path)
    create, update, ctx = _tools(sm)
    await _execute(create, ctx, objective="Old", completion_evidence="old artifact exists")

    denied = await _execute(update, ctx, action="replace", objective="New")
    assert "completion_evidence" in str(denied)

    ok = await _execute(
        update,
        ctx,
        action="replace",
        objective="New",
        completion_evidence="new artifact exists",
    )
    assert "Goal replaced" in str(ok)
    meta = sm.get_or_create("websocket:c1").metadata
    assert meta[GOAL_STATE_KEY]["completion_evidence"] == "new artifact exists"


@pytest.mark.asyncio
async def test_runtime_context_renders_pending_admission_branch(tmp_path):
    from nanobot.session.goal_state import set_goal_admission_pending

    sm = SessionManager(tmp_path)
    create = CreateGoalTool(sessions=sm)
    session = sm.get_or_create("websocket:c1")
    set_goal_admission_pending(session.metadata)
    sm.save(session)
    # Ordinary user turn: no /goal metadata.
    rc = _request_context(metadata={}, original_user_text="repo X please")

    block = await create._provide_runtime_context(rc)

    assert block is not None
    assert "Resolve the pending goal request" in block.content
    assert "Record the sustained goal promptly" not in block.content


@pytest.mark.asyncio
async def test_runtime_context_goal_turn_includes_routing_triage(tmp_path):
    sm = SessionManager(tmp_path)
    create = CreateGoalTool(sessions=sm)
    rc = _request_context()

    block = await create._provide_runtime_context(rc)

    assert block is not None
    assert "Route the request before recording a goal" in block.content
    assert "cron" in block.content
