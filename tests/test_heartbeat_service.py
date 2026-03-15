import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.heartbeat.service import HeartbeatService
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    provider = DummyProvider([])
    bus = MessageBus()

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        bus=bus,
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="no tool call", tool_calls=[])])
    bus = MessageBus()
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        bus=bus,
    )

    action, tasks = await service._decide("heartbeat content")
    assert action == "skip"
    assert tasks == ""


@pytest.mark.asyncio
async def test_tick_publishes_to_bus_when_decision_is_run(tmp_path) -> None:
    """Phase 1 run -> Phase 2 publish to bus with _source=heartbeat metadata."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    bus = MessageBus()
    pick_target_calls: list[tuple[str, str]] = []

    def _pick_target() -> tuple[str, str]:
        result = ("telegram", "chat-123")
        pick_target_calls.append(result)
        return result

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        bus=bus,
        pick_target=_pick_target,
    )

    await service._tick()

    # Verify message was published to bus
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert msg.content == "check open tasks"
    assert msg.channel == "telegram"
    assert msg.chat_id == "chat-123"
    assert msg.metadata.get("_source") == "heartbeat"
    assert msg.metadata.get("_task_context") == "check open tasks"
    assert pick_target_calls == [("telegram", "chat-123")]


@pytest.mark.asyncio
async def test_tick_does_not_publish_when_decision_is_skip(tmp_path) -> None:
    """Phase 1 skip -> no message published to bus."""
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "skip"},
                )
            ],
        )
    ])

    bus = MessageBus()
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        bus=bus,
    )

    await service._tick()

    # Verify no message was published
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_trigger_now_publishes_to_bus(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    bus = MessageBus()
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        bus=bus,
        pick_target=lambda: ("cli", "heartbeat"),
    )

    await service.trigger_now()

    # Verify message was published to bus
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert msg.content == "check open tasks"
    assert msg.metadata.get("_source") == "heartbeat"


@pytest.mark.asyncio
async def test_trigger_now_does_nothing_when_decision_is_skip(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "skip"},
                )
            ],
        )
    ])

    bus = MessageBus()
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        bus=bus,
    )

    await service.trigger_now()

    # Verify no message was published
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_pick_target_default(tmp_path) -> None:
    """Default pick_target returns ('cli', 'heartbeat')."""
    provider = DummyProvider([])
    bus = MessageBus()
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        bus=bus,
        # no pick_target provided
    )

    assert service.pick_target() == ("cli", "heartbeat")


@pytest.mark.asyncio
async def test_decide_retries_transient_error_then_succeeds(tmp_path, monkeypatch) -> None:
    provider = DummyProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        ),
    ])

    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    bus = MessageBus()
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        bus=bus,
    )

    action, tasks = await service._decide("heartbeat content")

    assert action == "run"
    assert tasks == "check open tasks"
    assert provider.calls == 2
    assert delays == [1]
