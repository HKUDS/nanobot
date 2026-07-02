from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.tools.context import RequestContext
from nanobot.agent.tools.cron import CronTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.types import CronJob, CronPayload, CronSchedule


class _CronStub:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def add_job(self, **kwargs):
        self.kwargs = kwargs

        class _Job:
            id = "job-1"
            name = "job"

        return _Job()

    def list_jobs(self):
        return []

    def remove_job(self, _job_id: str):
        return "not-found"


def test_cron_tool_stores_model_preset_override() -> None:
    cron = _CronStub()
    tool = CronTool(cron)
    tool.set_context(
        RequestContext(
            channel="websocket",
            chat_id="chat-1",
            session_key="websocket:chat-1",
        )
    )

    result = asyncio.run(tool.execute(
        action="add",
        message="Check status",
        every_seconds=60,
        model_preset="fast",
    ))

    assert "Created job" in result
    assert cron.kwargs is not None
    assert cron.kwargs["model"] is None
    assert cron.kwargs["model_preset"] == "fast"


def test_cron_tool_rejects_model_and_model_preset_together() -> None:
    cron = _CronStub()
    tool = CronTool(cron)
    tool.set_context(
        RequestContext(
            channel="websocket",
            chat_id="chat-1",
            session_key="websocket:chat-1",
        )
    )

    result = asyncio.run(tool.execute(
        action="add",
        message="Check status",
        every_seconds=60,
        model="model-a",
        model_preset="fast",
    ))

    assert "mutually exclusive" in result
    assert cron.kwargs is None


def test_cron_service_persists_model_override(tmp_path) -> None:
    from nanobot.cron.service import CronService

    service = CronService(tmp_path / "cron" / "jobs.json")
    job = service.add_job(
        name="model job",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="check",
        session_key="websocket:chat-1",
        origin_channel="websocket",
        origin_chat_id="chat-1",
        model="provider/model-x",
    )
    service._running = True
    try:
        service._load_store()
    finally:
        service._running = False

    reloaded = CronService(tmp_path / "cron" / "jobs.json").get_job(job.id)

    assert reloaded is not None
    assert reloaded.payload.model == "provider/model-x"
    assert reloaded.payload.model_preset is None


@pytest.mark.asyncio
async def test_bound_cron_runner_passes_model_preset_metadata() -> None:
    seen: dict[str, object] = {"records": []}

    class _Agent:
        tools = {}

        async def submit_cron_turn(self, msg: InboundMessage):
            seen["msg"] = msg
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="ok")

    class _Recorder:
        def write_run_record(self, run_id: str, record: dict) -> None:
            seen["records"].append((run_id, record))

    job = CronJob(
        id="job-1",
        name="preset job",
        payload=CronPayload(
            message="check",
            session_key="websocket:chat-1",
            origin_channel="websocket",
            origin_chat_id="chat-1",
            model_preset="fast",
        ),
    )

    await run_bound_cron_job(job, agent=_Agent(), cron=_Recorder())

    msg = seen["msg"]
    assert isinstance(msg, InboundMessage)
    assert msg.metadata["model_preset"] == "fast"
    records = seen["records"]
    assert records[0][1]["model_preset"] == "fast"


@pytest.mark.asyncio
async def test_submit_cron_turn_applies_model_override_for_turn(tmp_path) -> None:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    provider = MagicMock()
    provider.get_default_model.return_value = "base-model"
    provider.generation.max_tokens = 1024
    provider.generation.temperature = 0.2
    provider.generation.reasoning_effort = None
    seen: dict[str, object] = {}

    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as subagents:
        subagents.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(
            bus=MessageBus(),
            provider=provider,
            workspace=tmp_path,
            model="base-model",
        )

    class _CronTurns:
        async def submit(self, msg: InboundMessage):
            seen["during"] = (loop.model, loop.model_preset)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="ok")

    loop._cron_turns = _CronTurns()

    msg = InboundMessage(
        channel="websocket",
        sender_id="cron",
        chat_id="chat-1",
        content="check",
        metadata={"model": "override-model"},
        session_key_override="websocket:chat-1",
    )

    await loop.submit_cron_turn(msg)

    assert seen["during"] == ("override-model", None)
    assert loop.model == "base-model"
    assert loop.model_preset is None
