from __future__ import annotations

import pytest

from nanobot.agent.tools.context import RequestContext
from nanobot.goal.runtime import GoalExecutionPolicy
from nanobot.session.goal_state import GOAL_STATE_KEY
from nanobot.session.manager import SessionManager
from nanobot.session.turn_continuation import (
    INTERNAL_CONTINUATION_META,
    iteration_limit_context,
    record_iteration_limit,
    save_skip_for_turn,
    should_persist_user_message,
)


@pytest.mark.parametrize("status", ["completed", "cancelled", "blocked"])
async def test_goal_scope_reads_current_objective_and_closure(tmp_path, status):
    sessions = SessionManager(tmp_path)
    session = await sessions.state.get("feishu:c1")
    try:
        with GoalExecutionPolicy(sessions.state).scope(session.key, session.generation, persistent=True) as scope:
            assert await scope.continuation_prompt() is None
            await sessions.state.update_metadata(session.key, {
                GOAL_STATE_KEY: {"status": "active", "objective": "Finish the migration."},
            })
            assert "Finish the migration." in await scope.continuation_prompt()
            await sessions.state.update_metadata(session.key, {
                GOAL_STATE_KEY: {"status": "active", "objective": "A replacement."},
            })
            prompt = await scope.continuation_prompt()
            assert "A replacement." in prompt and "Finish the migration." not in prompt
            await sessions.state.update_metadata(session.key, {
                GOAL_STATE_KEY: {"status": status, "objective": "A replacement."},
            })
            assert await scope.continuation_prompt() is None
    finally:
        await sessions.state.aclose()


@pytest.mark.parametrize("operation", ["reset", "delete"])
async def test_goal_scope_does_not_continue_a_replaced_generation(tmp_path, operation):
    sessions = SessionManager(tmp_path)
    session = await sessions.state.get("cli:test")
    await sessions.state.update_metadata(session.key, {
        GOAL_STATE_KEY: {"status": "active", "objective": "Old objective."},
    })
    try:
        with GoalExecutionPolicy(sessions.state).scope(session.key, session.generation, persistent=True) as scope:
            assert "Old objective." in await scope.continuation_prompt()
            if operation == "reset":
                await sessions.state.reset(session.key)
            else:
                assert await sessions.state.delete(session.key)
            assert await scope.continuation_prompt() is None
            replacement = await sessions.state.get(session.key)
            await sessions.state.update_metadata(session.key, {
                GOAL_STATE_KEY: {"status": "active", "objective": "New generation's objective."},
            })
            assert replacement.generation != session.generation
            assert await scope.continuation_prompt() is None
        with GoalExecutionPolicy(sessions.state).scope(session.key, replacement.generation, persistent=True) as scope:
            assert "New generation's objective." in await scope.continuation_prompt()
    finally:
        await sessions.state.aclose()


async def test_iteration_limit_guidance_is_for_the_next_user_request_not_recovery(tmp_path):
    sessions = SessionManager(tmp_path)
    session = await sessions.state.get("cli:test")
    request = RequestContext(channel="cli", chat_id="test", session_key=session.key)
    try:
        await sessions.state.mutate_metadata(
            session.key, lambda metadata: record_iteration_limit(metadata, "max_iterations"),
        )
        context = await iteration_limit_context(sessions.state, request)
        assert context is not None and "Follow the current request" in context.content
        recovery = RequestContext(
            channel="cli", chat_id="test", session_key=session.key,
            metadata={INTERNAL_CONTINUATION_META: True},
        )
        assert await iteration_limit_context(sessions.state, recovery) is None
        await sessions.state.mutate_metadata(
            session.key, lambda metadata: record_iteration_limit(metadata, "completed"),
        )
        assert await iteration_limit_context(sessions.state, request) is None
    finally:
        await sessions.state.aclose()


def test_explicit_recovery_does_not_persist_a_synthetic_user_input():
    metadata = {INTERNAL_CONTINUATION_META: True}
    assert not should_persist_user_message(metadata)
    assert save_skip_for_turn(
        message_metadata=metadata, initial_message_count=3, input_persisted_early=False,
    ) == 3
    assert should_persist_user_message(None)


def test_save_skip_unchanged_for_standalone_current_message():
    assert save_skip_for_turn(
        message_metadata=None, initial_message_count=3, input_persisted_early=True,
    ) == 3
    assert save_skip_for_turn(
        message_metadata=None, initial_message_count=3, input_persisted_early=False,
    ) == 2
