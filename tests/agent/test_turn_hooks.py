import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.turn_hooks import AgentTurnHookSpec, build_agent_turn_hook


class RecordingHook(AgentHook):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._events.append(f"hook:{context.iteration}")


@pytest.mark.asyncio
async def test_turn_hook_builder_runs_progress_hook_before_extra_hooks() -> None:
    events: list[str] = []

    hook = build_agent_turn_hook(AgentTurnHookSpec(
        on_iteration=lambda iteration: events.append(f"progress:{iteration}"),
        registered_hooks=[RecordingHook(events)],
    ))

    await hook.before_iteration(AgentHookContext(iteration=2, messages=[]))

    assert events == ["progress:2", "hook:2"]


@pytest.mark.asyncio
async def test_turn_hook_builder_skips_extra_hooks_for_ephemeral_turns_by_default() -> None:
    events: list[str] = []

    hook = build_agent_turn_hook(AgentTurnHookSpec(
        registered_hooks=[RecordingHook(events)],
        ephemeral=True,
    ))

    await hook.before_iteration(AgentHookContext(iteration=1, messages=[]))

    assert events == []


@pytest.mark.asyncio
async def test_turn_hook_builder_can_include_extra_hooks_for_ephemeral_turns() -> None:
    events: list[str] = []

    hook = build_agent_turn_hook(AgentTurnHookSpec(
        registered_hooks=[RecordingHook(events)],
        ephemeral=True,
        run_extra_hooks_for_ephemeral=True,
    ))

    await hook.before_iteration(AgentHookContext(iteration=1, messages=[]))

    assert events == ["hook:1"]
