from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.types import CronJob, CronPayload


class _FakeAgent:
    def __init__(self) -> None:
        self.tools = ToolRegistry()
        self.messages: list[InboundMessage] = []

    async def submit_cron_turn(self, msg: InboundMessage) -> OutboundMessage:
        self.messages.append(msg)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="done")


class _FakeRecorder:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def write_run_record(self, run_id: str, record: dict[str, Any]) -> None:
        self.records.append((run_id, record))


@pytest.mark.asyncio
async def test_bound_cron_routes_target_but_keeps_origin_session() -> None:
    agent = _FakeAgent()
    recorder = _FakeRecorder()
    job = CronJob(
        id="job1",
        name="health",
        payload=CronPayload(
            message="check health",
            session_key="websocket:origin-topic",
            origin_channel="websocket",
            origin_chat_id="origin-topic",
            delivery_channel="slack",
            delivery_chat_id="C123",
        ),
    )

    result = await run_bound_cron_job(job, agent=agent, cron=recorder)

    assert result == "done"
    message = agent.messages[0]
    assert message.channel == "slack"
    assert message.chat_id == "C123"
    assert message.session_key_override == "websocket:origin-topic"
    assert recorder.records[0][1]["delivery"] == {
        "channel": "slack",
        "chat_id": "C123",
    }


@pytest.mark.asyncio
async def test_bound_cron_without_target_delivers_to_origin() -> None:
    agent = _FakeAgent()
    recorder = _FakeRecorder()
    job = CronJob(
        id="job1",
        name="health",
        payload=CronPayload(
            message="check health",
            session_key="websocket:origin-topic",
            origin_channel="websocket",
            origin_chat_id="origin-topic",
        ),
    )

    await run_bound_cron_job(job, agent=agent, cron=recorder)

    message = agent.messages[0]
    assert message.channel == "websocket"
    assert message.chat_id == "origin-topic"
    assert message.session_key_override == "websocket:origin-topic"
