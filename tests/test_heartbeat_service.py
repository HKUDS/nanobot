import asyncio

import pytest

from nanobot.heartbeat.service import (
    HeartbeatService,
    _is_heartbeat_ok_response,
)


def test_heartbeat_ok_response_requires_exact_token() -> None:
    assert _is_heartbeat_ok_response("HEARTBEAT_OK")
    assert _is_heartbeat_ok_response("`HEARTBEAT_OK`")
    assert _is_heartbeat_ok_response("**HEARTBEAT_OK**")

    assert not _is_heartbeat_ok_response("HEARTBEAT_OK, done")
    assert not _is_heartbeat_ok_response("done HEARTBEAT_OK")
    assert not _is_heartbeat_ok_response("HEARTBEAT_NOT_OK")


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
