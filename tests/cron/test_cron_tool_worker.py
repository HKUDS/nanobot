"""Worker-thread regressions for live CronTool mutations."""

import asyncio
import json
import threading

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.cron import CronTool
from nanobot.cron.service import CronService


@pytest.mark.asyncio
async def test_cron_tool_add_on_started_service_is_durable_and_rearms_owner_loop(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path, max_sleep_ms=60_000)
    await service.start()

    owner_thread_id = threading.get_ident()
    initial_timer = service._timer_task
    worker_thread_ids: list[int] = []
    arm_thread_ids: list[int] = []
    timer_rearmed = asyncio.Event()
    tool = CronTool(service)

    original_execute_sync = tool._execute_sync

    def tracked_execute_sync(*args, **kwargs):
        worker_thread_ids.append(threading.get_ident())
        return original_execute_sync(*args, **kwargs)

    original_arm_timer = service._arm_timer

    def tracked_arm_timer() -> None:
        arm_thread_ids.append(threading.get_ident())
        original_arm_timer()
        timer_rearmed.set()

    monkeypatch.setattr(tool, "_execute_sync", tracked_execute_sync)
    monkeypatch.setattr(service, "_arm_timer", tracked_arm_timer)

    try:
        with request_context(
            RequestContext(
                channel="websocket",
                chat_id="acceptance-chat",
                session_key="websocket:acceptance-chat",
            )
        ):
            result = await tool.execute(
                action="add",
                name="Acceptance reminder",
                message="Check the acceptance result",
                every_seconds=3600,
            )

        await asyncio.wait_for(timer_rearmed.wait(), timeout=1)

        assert result.startswith("Created job 'Acceptance reminder'")
        assert "no running event loop" not in result.lower()
        assert worker_thread_ids
        assert all(thread_id != owner_thread_id for thread_id in worker_thread_ids)
        assert arm_thread_ids and set(arm_thread_ids) == {owner_thread_id}
        assert service._timer_task is not None
        assert service._timer_task is not initial_timer
        assert not service._timer_task.done()

        stored = json.loads(store_path.read_text(encoding="utf-8"))
        assert len(stored["jobs"]) == 1
        assert stored["jobs"][0]["name"] == "Acceptance reminder"
        assert stored["jobs"][0]["payload"]["sessionKey"] == "websocket:acceptance-chat"

        reloaded_jobs = CronService(store_path).list_jobs(include_disabled=True)
        assert len(reloaded_jobs) == 1
        assert reloaded_jobs[0].name == "Acceptance reminder"
    finally:
        service.stop()
        await asyncio.sleep(0)
