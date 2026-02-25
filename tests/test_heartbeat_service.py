import asyncio

import pytest

from nanobot.heartbeat.service import HeartbeatService
from nanobot.providers.base import LLMResponse, ToolCallRequest


class MockHeartbeatProvider:
    """Minimal provider that returns skip for heartbeat decisions."""

    async def chat(self, messages, tools=None, model=None):
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="1",
                    name="heartbeat",
                    arguments={"action": "skip", "tasks": ""},
                )
            ],
        )


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    provider = MockHeartbeatProvider()
    (tmp_path / "HEARTBEAT.md").write_text("# Tasks\n\nNothing to do.")

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test",
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)
