from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from pathlib import Path

import pytest

from nanobot.agent.automation_turns import AutomationTurnAcceptedCancellation
from nanobot.agent.cron_turns import CronTurnCoordinator
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule


class _NoCronToolRegistry:
    def get(self, _name: str) -> None:
        return None


class _CoordinatedAgent:
    def __init__(self) -> None:
        self.tools = _NoCronToolRegistry()
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.coordinator = CronTurnCoordinator(
            publish_inbound=self.inbound.put,
            dispatch=lambda _msg: asyncio.sleep(0),
            is_running=lambda: True,
        )

    async def submit_cron_turn(
        self,
        msg: InboundMessage,
    ) -> OutboundMessage | None:
        return await self.coordinator.submit(msg)


@pytest.mark.asyncio
async def test_accepted_bound_turn_cancellation_advances_durable_schedule(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "cron" / "jobs.json"
    agent = _CoordinatedAgent()
    service = CronService(store_path)
    job = service.add_job(
        name="accepted reminder",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="check accepted work",
        session_key="websocket:chat-1",
        origin_channel="websocket",
        origin_chat_id="chat-1",
    )

    async def on_job(current: CronJob) -> str | None:
        return await run_bound_cron_job(current, agent=agent, cron=service)

    service.on_job = on_job
    work_accepted = asyncio.Event()
    release_work = asyncio.Event()
    effects: list[str] = []

    async def agent_worker() -> None:
        msg = await agent.inbound.get()
        work_accepted.set()
        await release_work.wait()
        effects.append(msg.content)
        agent.coordinator.complete(msg)

    worker = asyncio.create_task(agent_worker())
    run = asyncio.create_task(service.run_job(job.id))
    try:
        await asyncio.wait_for(work_accepted.wait(), timeout=1)
        run.cancel()
        with pytest.raises(AutomationTurnAcceptedCancellation):
            await asyncio.wait_for(run, timeout=1)

        # Cancellation is prompt and the independently-owned agent turn can
        # finish later, while the cron schedule is already durable.
        assert effects == []
        persisted = CronService(store_path).get_job(job.id)
        assert persisted is not None
        assert persisted.state.last_status == "ok"
        assert persisted.state.last_error is None
        assert persisted.state.last_run_at_ms is not None
        assert persisted.state.next_run_at_ms is not None
        assert persisted.state.next_run_at_ms > persisted.state.last_run_at_ms
        assert len(persisted.state.run_history) == 1
        assert persisted.state.run_history[0].status == "ok"

        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (store_path.parent / "runs").glob("*.json")
        ]
        assert len(records) == 1
        assert records[0]["status"] == "accepted"

        replayed: list[str] = []

        async def replay_job(current: CronJob) -> None:
            replayed.append(current.id)

        restarted = CronService(store_path, on_job=replay_job)
        restarted._running = True
        restarted._arm_timer = lambda: None
        try:
            await restarted._on_timer()
        finally:
            restarted.stop()
        assert replayed == []

        release_work.set()
        await asyncio.wait_for(worker, timeout=1)
        assert effects == [records[0]["rendered_prompt"]]
    finally:
        release_work.set()
        if not run.done():
            run.cancel()
        if not worker.done():
            worker.cancel()
        with suppress(asyncio.CancelledError):
            await run
        with suppress(asyncio.CancelledError):
            await worker
