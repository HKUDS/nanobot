import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.runtime_events import (
    RuntimeEventBus,
    RuntimeEventContext,
    RuntimeEventPublisher,
    RuntimeModelChanged,
    SessionTurnStarted,
    TurnCompleted,
    TurnModelAttempted,
    TurnRunStatusChanged,
)


@pytest.mark.asyncio
async def test_runtime_event_bus_filters_by_event_type() -> None:
    bus = RuntimeEventBus()
    seen: list[str] = []

    async def handle_run_status(event: TurnRunStatusChanged) -> None:
        seen.append(event.status)

    bus.subscribe(handle_run_status, TurnRunStatusChanged)

    await bus.publish(RuntimeModelChanged(model="m", model_preset=None))
    await bus.publish(
        TurnRunStatusChanged(
            context=RuntimeEventContext(
                channel="cli",
                chat_id="direct",
                session_key="cli:direct",
            ),
            status="running",
        )
    )

    assert seen == ["running"]


@pytest.mark.asyncio
async def test_runtime_event_bus_keeps_catch_all_subscription() -> None:
    bus = RuntimeEventBus()
    seen: list[str] = []

    def handle_any(event) -> None:
        seen.append(type(event).__name__)

    bus.subscribe(handle_any)

    await bus.publish(RuntimeModelChanged(model="m", model_preset=None))

    assert seen == ["RuntimeModelChanged"]


@pytest.mark.asyncio
async def test_runtime_event_publisher_builds_context_from_inbound_message() -> None:
    bus = RuntimeEventBus()
    seen: list[object] = []
    publisher = RuntimeEventPublisher(bus)
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-a",
        content="hello",
        metadata={"trace_id": "turn-1"},
    )

    bus.subscribe(seen.append)

    await publisher.session_turn_started(msg, "websocket:chat-a")
    await publisher.run_status_changed(
        msg,
        "websocket:chat-a",
        "running",
        started_at=12.5,
    )

    started = seen[0]
    running = seen[1]
    assert isinstance(started, SessionTurnStarted)
    assert started.context.channel == "websocket"
    assert started.context.chat_id == "chat-a"
    assert started.context.session_key == "websocket:chat-a"
    assert started.context.metadata == {"trace_id": "turn-1"}
    assert started.context.metadata is not msg.metadata
    assert isinstance(running, TurnRunStatusChanged)
    assert running.status == "running"
    assert running.started_at == 12.5


@pytest.mark.asyncio
async def test_runtime_event_publisher_routes_turn_model_attempt() -> None:
    bus = RuntimeEventBus()
    seen: list[object] = []
    publisher = RuntimeEventPublisher(bus)
    bus.subscribe(seen.append, TurnModelAttempted)

    await publisher.turn_model_attempted(
        channel="websocket",
        chat_id="chat-model",
        session_key="websocket:chat-model",
        metadata={"webui": True},
        model="deepseek/deepseek-chat",
        provider="deepseek",
        primary_model="openai/gpt-5",
        fallback_index=1,
    )

    event = seen[0]
    assert isinstance(event, TurnModelAttempted)
    assert event.context.chat_id == "chat-model"
    assert event.model == "deepseek/deepseek-chat"
    assert event.primary_model == "openai/gpt-5"
    assert event.provider == "deepseek"
    assert event.fallback_index == 1


@pytest.mark.asyncio
async def test_runtime_event_publisher_consumes_turn_metadata_on_complete() -> None:
    bus = RuntimeEventBus()
    seen: list[object] = []
    publisher = RuntimeEventPublisher(bus)

    bus.subscribe(seen.append)
    publisher.record_turn_runtime("cli:direct", "runtime")
    publisher.record_turn_latency("cli:direct", 123)

    await publisher.turn_completed(
        channel="cli",
        chat_id="direct",
        session_key="cli:direct",
        metadata={"source": "test"},
    )
    await publisher.turn_completed(
        channel="cli",
        chat_id="direct",
        session_key="cli:direct",
        metadata=None,
    )

    first = seen[0]
    second = seen[1]
    assert isinstance(first, TurnCompleted)
    assert first.context.metadata == {"source": "test"}
    assert first.latency_ms == 123
    assert first.runtime == "runtime"
    assert isinstance(second, TurnCompleted)
    assert second.latency_ms is None
    assert second.runtime is None
