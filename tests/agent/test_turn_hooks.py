import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext, AgentTurnHookContext
from nanobot.agent.turn_hooks import AgentTurnHookSpec, build_agent_turn_hook


class RecordingHook(AgentHook):
    def __init__(self, events: list[str], label: str = "hook") -> None:
        super().__init__()
        self._events = events
        self._label = label

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._events.append(f"{self._label}:{context.iteration}")


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
async def test_turn_hook_builder_runs_registered_hooks_before_turn_hooks() -> None:
    events: list[str] = []

    hook = build_agent_turn_hook(AgentTurnHookSpec(
        on_iteration=lambda iteration: events.append(f"progress:{iteration}"),
        registered_hooks=[RecordingHook(events, "registered")],
        turn_hooks=[RecordingHook(events, "turn")],
    ))

    await hook.before_iteration(AgentHookContext(iteration=2, messages=[]))

    assert events == ["progress:2", "registered:2", "turn:2"]


@pytest.mark.asyncio
async def test_turn_hook_builder_runs_factories_with_matching_registration_order(
    tmp_path,
) -> None:
    events: list[str] = []
    captured: list[AgentTurnHookContext] = []

    def factory(label: str):
        def _create(context: AgentTurnHookContext) -> AgentHook:
            captured.append(context)
            return RecordingHook(events, label)

        return _create

    hook = build_agent_turn_hook(AgentTurnHookSpec(
        on_iteration=lambda iteration: events.append(f"progress:{iteration}"),
        channel="websocket",
        chat_id="chat-1",
        message_id="msg-1",
        session_key="websocket:chat-1",
        workspace=tmp_path,
        metadata={"source": "test"},
        registered_hook_factories=[factory("registered_factory")],
        registered_hooks=[RecordingHook(events, "registered")],
        turn_hook_factories=[factory("turn_factory")],
        turn_hooks=[RecordingHook(events, "turn")],
    ))

    await hook.before_iteration(AgentHookContext(iteration=2, messages=[]))

    assert events == [
        "progress:2",
        "registered_factory:2",
        "registered:2",
        "turn_factory:2",
        "turn:2",
    ]
    assert [context.workspace for context in captured] == [tmp_path, tmp_path]
    assert [context.channel for context in captured] == ["websocket", "websocket"]
    assert [context.chat_id for context in captured] == ["chat-1", "chat-1"]
    assert [context.message_id for context in captured] == ["msg-1", "msg-1"]
    assert [context.session_key for context in captured] == [
        "websocket:chat-1",
        "websocket:chat-1",
    ]
    assert [context.metadata for context in captured] == [
        {"source": "test"},
        {"source": "test"},
    ]


@pytest.mark.asyncio
async def test_turn_hook_builder_skips_extra_hooks_for_ephemeral_turns_by_default() -> None:
    events: list[str] = []
    factory_calls: list[str] = []

    def factory(context: AgentTurnHookContext) -> AgentHook:
        factory_calls.append(context.channel)
        return RecordingHook(events, "factory")

    hook = build_agent_turn_hook(AgentTurnHookSpec(
        registered_hook_factories=[factory],
        registered_hooks=[RecordingHook(events)],
        ephemeral=True,
    ))

    await hook.before_iteration(AgentHookContext(iteration=1, messages=[]))

    assert events == []
    assert factory_calls == []


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
