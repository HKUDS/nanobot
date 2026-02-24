import asyncio

import pytest

from nanobot.heartbeat.service import (
    HEARTBEAT_OK_TOKEN,
    HeartbeatService,
)


def test_heartbeat_ok_detection() -> None:
    def is_ok(response: str) -> bool:
        return HEARTBEAT_OK_TOKEN in response.upper()

    assert is_ok("HEARTBEAT_OK")
    assert is_ok("`HEARTBEAT_OK`")
    assert is_ok("**HEARTBEAT_OK**")
    assert is_ok("heartbeat_ok")
    assert is_ok("HEARTBEAT_OK.")

    assert not is_ok("HEARTBEAT_NOT_OK")
    assert not is_ok("all good")


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    async def _on_heartbeat(_: str) -> str:
        return "HEARTBEAT_OK"

    service = HeartbeatService(
        workspace=tmp_path,
        on_heartbeat=_on_heartbeat,
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)
