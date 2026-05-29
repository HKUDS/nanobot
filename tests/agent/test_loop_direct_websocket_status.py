from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMResponse


def _make_loop(tmp_path):
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = GenerationSettings(max_tokens=0)
    provider.estimate_prompt_tokens.return_value = (0, "test-counter")
    response = LLMResponse(content="done", tool_calls=[])
    provider.chat_with_retry = AsyncMock(return_value=response)
    provider.chat_stream_with_retry = AsyncMock(return_value=response)

    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


@pytest.mark.asyncio
async def test_process_direct_websocket_clears_run_status(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    response = await loop.process_direct(
        "deliver reminder",
        session_key="cron:reminder-1",
        channel="websocket",
        chat_id="chat-1",
    )

    assert response is not None
    assert response.content == "done"

    events = []
    while loop.bus.outbound_size:
        events.append(await loop.bus.consume_outbound())

    statuses = [
        event.metadata
        for event in events
        if event.metadata.get("_goal_status") is True
    ]
    assert [status["goal_status"] for status in statuses] == ["running", "idle"]
    assert isinstance(statuses[0].get("started_at"), float)
    assert "started_at" not in statuses[1]
