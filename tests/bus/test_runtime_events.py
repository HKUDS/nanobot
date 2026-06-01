import pytest

from nanobot.bus.runtime_events import (
    RuntimeEventBus,
    RuntimeEventContext,
    RuntimeModelChanged,
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
