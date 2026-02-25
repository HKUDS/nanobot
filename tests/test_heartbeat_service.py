import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.heartbeat.service import HeartbeatService


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path: Path) -> None:
    """Starting the service twice does not create a second task."""
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=MagicMock(has_tool_calls=False))
    async def _on_execute(_: str) -> str:
        return "ok"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
        on_execute=_on_execute,
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)
