"""Tests for WebSocket turn timing strip bookkeeping."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.hook import AgentRunHookContext, AgentTurnHookContext
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import GoalStatusEvent, TurnEndEvent, TurnModelUpdatedEvent
from nanobot.bus.runtime_events import RuntimeEventBus, RuntimeEventContext, TurnRuntimeAdmitted
from nanobot.providers.base import GenerationSettings
from nanobot.session import webui_turns as wth
from nanobot.session.manager import SessionManager
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.webui.metadata import (
    WEBSOCKET_TURN_OWNER_METADATA_KEY,
    WEBUI_TURN_METADATA_KEY,
)


@pytest.fixture(autouse=True)
def _clear_turn_wall_clock() -> None:
    wth._WEBSOCKET_ACTIVE_TURNS.clear()
    wth._COMPLETED_WEBUI_TURN_RUNTIMES.clear()
    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    wth._WEBSOCKET_TURN_IDS.clear()
    wth._WEBSOCKET_TURN_OWNERS.clear()
    yield
    wth._WEBSOCKET_ACTIVE_TURNS.clear()
    wth._COMPLETED_WEBUI_TURN_RUNTIMES.clear()
    wth._WEBSOCKET_TURN_WALL_STARTED_AT.clear()
    wth._WEBSOCKET_TURN_IDS.clear()
    wth._WEBSOCKET_TURN_OWNERS.clear()


@pytest.mark.asyncio
async def test_publish_turn_run_status_running_records_wall_clock() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-a",
        content="hi",
        metadata={"webui_turn_id": "turn-a"},
    )

    await wth.publish_turn_run_status(bus, msg, "running")

    assert "chat-a" in wth._WEBSOCKET_TURN_WALL_STARTED_AT
    t0 = wth.websocket_turn_wall_started_at("chat-a")
    assert isinstance(t0, float)
    assert wth.websocket_turn_id("chat-a") == "turn-a"
    call = bus.publish_outbound.await_args[0][0]
    assert call.chat_id == "chat-a"
    assert isinstance(call.event, GoalStatusEvent)
    assert call.event.started_at == t0


@pytest.mark.asyncio
async def test_publish_turn_run_status_reuses_explicit_wall_clock() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="websocket", sender_id="u", chat_id="chat-a", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running", started_at=1234.5)

    assert wth.websocket_turn_wall_started_at("chat-a") == 1234.5
    call = bus.publish_outbound.await_args[0][0]
    assert isinstance(call.event, GoalStatusEvent)
    assert call.event.started_at == 1234.5


@pytest.mark.asyncio
async def test_publish_turn_run_status_idle_retains_registry_until_delivery() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-b",
        content="hi",
        metadata={"webui_turn_id": "turn-b"},
    )

    await wth.publish_turn_run_status(bus, msg, "running")
    assert wth.websocket_turn_wall_started_at("chat-b") is not None
    assert wth.websocket_turn_id("chat-b") == "turn-b"

    await wth.publish_turn_run_status(bus, msg, "idle")
    assert wth.websocket_turn_wall_started_at("chat-b") is not None
    assert wth.websocket_turn_id("chat-b") == "turn-b"


def test_clear_websocket_turn_only_clears_matching_owner() -> None:
    wth._WEBSOCKET_TURN_WALL_STARTED_AT["chat-b"] = 1234.5
    wth._WEBSOCKET_TURN_IDS["chat-b"] = "turn-new"
    wth._WEBSOCKET_TURN_OWNERS["chat-b"] = "owner-new"

    assert wth.clear_websocket_turn_if_current("chat-b", "owner-old") is False
    assert wth.websocket_turn_wall_started_at("chat-b") == 1234.5
    assert wth.websocket_turn_id("chat-b") == "turn-new"

    assert wth.clear_websocket_turn_if_current("chat-b", "owner-new") is True
    assert wth.websocket_turn_wall_started_at("chat-b") is None
    assert wth.websocket_turn_id("chat-b") is None


def test_new_or_discarded_chat_drops_unclaimed_completed_runtime() -> None:
    runtime = LLMRuntime(
        provider=MagicMock(),
        model="deep-model",
        generation=GenerationSettings(),
        context_window_tokens=100_000,
    )
    wth.remember_completed_websocket_turn_runtime("chat-b", "turn-old", runtime)

    assert wth.register_queued_websocket_turn_if_idle("chat-b", "turn-new") is not None
    assert wth.take_completed_websocket_turn_runtime("chat-b", "turn-old") is None

    wth.remember_completed_websocket_turn_runtime("chat-b", "turn-new", runtime)
    wth.clear_websocket_turns("chat-b")
    assert wth.take_completed_websocket_turn_runtime("chat-b", "turn-new") is None


@pytest.mark.asyncio
async def test_ownerless_turns_receive_distinct_internal_owners() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    first = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-ownerless",
        content="first",
    )
    second = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-ownerless",
        content="second",
    )

    await wth.publish_turn_run_status(bus, first, "running")
    first_owner = first.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]
    await wth.publish_turn_run_status(bus, second, "running")
    second_owner = second.metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY]

    assert first_owner != second_owner
    assert wth.clear_websocket_turn_if_current("chat-ownerless", first_owner) is True
    assert wth._WEBSOCKET_TURN_OWNERS["chat-ownerless"] == second_owner
    assert wth.websocket_turn_wall_started_at("chat-ownerless") is not None
    assert wth.clear_websocket_turn_if_current("chat-ownerless", second_owner) is True


@pytest.mark.asyncio
async def test_publish_turn_run_status_non_websocket_noop_registry() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    msg = InboundMessage(channel="telegram", sender_id="u", chat_id="1", content="hi")

    await wth.publish_turn_run_status(bus, msg, "running")

    assert wth._WEBSOCKET_TURN_WALL_STARTED_AT == {}
    assert wth._WEBSOCKET_TURN_IDS == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(("stop_reason", "successful"), [("completed", True), ("error", False)])
async def test_webui_turn_result_hook_records_runner_outcome_by_owner(
    stop_reason: str,
    successful: bool,
) -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    metadata = {
        "webui": True,
        WEBUI_TURN_METADATA_KEY: "turn-result",
        WEBSOCKET_TURN_OWNER_METADATA_KEY: "owner-result",
    }
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-result",
        content="hi",
        metadata=metadata,
    )
    await wth.publish_turn_run_status(bus, msg, "running")

    hook = wth.create_webui_turn_result_hook(AgentTurnHookContext(
        channel="websocket",
        chat_id="chat-result",
        metadata=metadata,
    ))
    assert hook is not None
    await hook.on_finally(AgentRunHookContext(messages=[], stop_reason=stop_reason))

    assert wth.websocket_turn_successful("chat-result", "owner-result") is successful


@pytest.mark.asyncio
async def test_webui_turn_completion_defaults_missing_runner_outcome_to_failed(tmp_path) -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    metadata = {
        "webui": True,
        WEBUI_TURN_METADATA_KEY: "turn-missing-result",
        WEBSOCKET_TURN_OWNER_METADATA_KEY: "owner-missing-result",
    }
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-missing-result",
        content="hi",
        metadata=metadata,
    )
    await wth.publish_turn_run_status(bus, msg, "running")
    bus.publish_outbound.reset_mock()
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus,
        sessions=SessionManager(tmp_path),
        schedule_background=MagicMock(),
    )

    await coordinator.handle_turn_end(
        msg,
        session_key="websocket:chat-missing-result",
        latency_ms=None,
    )

    outbound = bus.publish_outbound.await_args.args[0]
    assert isinstance(outbound.event, TurnEndEvent)
    assert outbound.event.successful is False


@pytest.mark.asyncio
async def test_successful_webui_turn_hands_off_completed_runtime_once(tmp_path) -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    metadata = {
        "webui": True,
        WEBUI_TURN_METADATA_KEY: "turn-completed",
        WEBSOCKET_TURN_OWNER_METADATA_KEY: "owner-completed",
    }
    msg = InboundMessage(
        channel="websocket",
        sender_id="u",
        chat_id="chat-completed",
        content="hi",
        metadata=metadata,
    )
    await wth.publish_turn_run_status(bus, msg, "running")
    assert wth.mark_websocket_turn_successful("chat-completed", "owner-completed", True)
    runtime = LLMRuntime(
        provider=MagicMock(),
        model="deep-model",
        generation=GenerationSettings(),
        context_window_tokens=100_000,
    )
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus,
        sessions=SessionManager(tmp_path),
        schedule_background=MagicMock(),
    )

    await coordinator.handle_turn_end(
        msg,
        session_key="websocket:chat-completed",
        latency_ms=None,
        runtime=runtime,
    )

    assert wth.take_completed_websocket_turn_runtime(
        "chat-completed",
        "turn-completed",
    ) is runtime
    assert wth.take_completed_websocket_turn_runtime(
        "chat-completed",
        "turn-completed",
    ) is None


@pytest.mark.asyncio
async def test_fallback_model_is_scoped_to_its_websocket_chat() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    observer = wth.build_webui_fallback_model_observer(bus)

    runtime = LLMRuntime(
        provider=MagicMock(),
        model="openai/gpt-4.1",
        generation=GenerationSettings(),
        context_window_tokens=16_000,
        model_preset="Deep Research",
    )
    with request_context(
        RequestContext(
            channel="websocket",
            chat_id="chat-model",
            runtime=runtime,
            metadata={"webui": True},
        )
    ):
        await observer("deepseek/deepseek-chat")

    outbound = bus.publish_outbound.await_args.args[0]
    assert outbound.channel == "websocket"
    assert outbound.chat_id == "chat-model"
    assert outbound.metadata == {"webui": True}
    assert isinstance(outbound.event, TurnModelUpdatedEvent)
    assert outbound.event.model == "deepseek/deepseek-chat"
    assert outbound.event.model_preset == "Deep Research"


@pytest.mark.asyncio
async def test_admitted_runtime_publishes_chat_scoped_model_and_preset(tmp_path) -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    runtime_events = RuntimeEventBus()
    coordinator = wth.WebuiTurnCoordinator(
        bus=bus,
        sessions=SessionManager(tmp_path),
        schedule_background=lambda coro: coro.close(),
    )
    coordinator.subscribe(runtime_events)
    runtime = LLMRuntime(
        provider=MagicMock(),
        model="openai-codex/gpt-5.6",
        generation=GenerationSettings(),
        context_window_tokens=262_144,
        model_preset="Codex",
    )

    await runtime_events.publish(
        TurnRuntimeAdmitted(
            context=RuntimeEventContext(
                channel="websocket",
                chat_id="chat-model",
                session_key="websocket:chat-model",
                metadata={"webui": True},
            ),
            runtime=runtime,
        )
    )

    outbound = bus.publish_outbound.await_args.args[0]
    assert outbound.channel == "websocket"
    assert outbound.chat_id == "chat-model"
    assert isinstance(outbound.event, TurnModelUpdatedEvent)
    assert outbound.event.model == "openai-codex/gpt-5.6"
    assert outbound.event.model_preset == "Codex"


@pytest.mark.asyncio
async def test_fallback_model_ignores_non_websocket_requests() -> None:
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    observer = wth.build_webui_fallback_model_observer(bus)

    with request_context(RequestContext(channel="telegram", chat_id="chat-model")):
        await observer("fallback")

    bus.publish_outbound.assert_not_awaited()
