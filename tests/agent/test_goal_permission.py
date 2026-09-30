import asyncio

import pytest

from nanobot.agent.goal_permission import (
    GoalInputScope,
    goal_mutation_allowed,
    goal_mutation_permission,
    revoke_goal_mutation_permission,
)
from nanobot.bus.events import InboundMessage


def goal_message(**overrides):
    fields = dict(
        channel="websocket", sender_id="user", chat_id="test", content="Execute the plan",
        metadata={"goal_requested": True},
    )
    fields.update(overrides)
    return InboundMessage(**fields)


@pytest.mark.parametrize("overrides", [
    {"channel": "system", "input_role": "user"},
    {"sender_id": "subagent"},
    {"input_role": "system"},
    {"metadata": {"goal_requested": True, "_internal_continuation": True}},
    {"metadata": {"goal_requested": True, "_cron_trigger": {"job_id": "job"}}},
    {"metadata": {"goal_requested": True, "_local_trigger": {"trigger_id": "trigger"}}},
])
def test_background_input_cannot_authorize_initial_or_injected_work(overrides):
    message = goal_message(**overrides)
    with goal_mutation_permission(True):
        with GoalInputScope(message) as scope:
            assert goal_mutation_allowed() is False
            scope.consume_inputs([message])
            assert goal_mutation_allowed() is False
        assert goal_mutation_allowed() is True


def test_completion_requires_a_new_explicit_request_to_reauthorize():
    with GoalInputScope(goal_message()) as scope:
        assert goal_mutation_allowed() is True
        revoke_goal_mutation_permission()
        scope.consume_inputs([goal_message(content="ok", metadata={})])
        assert goal_mutation_allowed() is False
        scope.consume_inputs([goal_message(content="Execute another plan")])
        assert goal_mutation_allowed() is True
    assert goal_mutation_allowed() is False


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_injected_permission_is_cleared_on_abnormal_exit(error):
    with pytest.raises(error):
        with GoalInputScope() as scope:
            assert goal_mutation_allowed() is False
            scope.consume_inputs([goal_message()])
            assert goal_mutation_allowed() is True
            raise error()
    assert goal_mutation_allowed() is False
