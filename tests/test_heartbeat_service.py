import asyncio

import pytest

from nanobot.heartbeat.service import (
    HeartbeatService,
)


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    async def _on_heartbeat(_: str) -> str:
        return "HEARTBEAT_OK"

    from unittest.mock import MagicMock
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="test-model",
        on_execute=_on_heartbeat,
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)
