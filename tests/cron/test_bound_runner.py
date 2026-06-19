from __future__ import annotations

from typing import Any

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.session_turns import CRON_TRIGGER_META
from nanobot.cron.types import CronJob, CronPayload


class _FakeAgent:
    model = "test-model"
    provider = object()
    tools: dict[str, object] = {}

    def __init__(self, content: str = "important update") -> None:
        self.content = content
        self.messages: list[InboundMessage] = []

    async def submit_cron_turn(self, msg: InboundMessage) -> OutboundMessage:
        self.messages.append(msg)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=self.content)


class _FakeCron:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def write_run_record(self, run_id: str, record: dict[str, Any]) -> None:
        self.records.append((run_id, record))


def _job() -> CronJob:
    return CronJob(
        id="job-1",
        name="Repo check",
        payload=CronPayload(
            message="Check repository health.",
            session_key="websocket:chat-1",
            origin_channel="websocket",
            origin_chat_id="chat-1",
        ),
    )


@pytest.mark.asyncio
async def test_bound_cron_delivers_when_post_run_evaluator_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions: list[bool] = []
    delivered: list[tuple[OutboundMessage, bool, str | None]] = []

    async def _allow(*_args: Any, default_notify: bool = False, **_kwargs: Any) -> bool:
        decisions.append(default_notify)
        return True

    async def _deliver(
        msg: OutboundMessage,
        *,
        record: bool = False,
        session_key: str | None = None,
    ) -> None:
        delivered.append((msg, record, session_key))

    monkeypatch.setattr("nanobot.cron.bound_runner.evaluate_response", _allow)

    response = await run_bound_cron_job(_job(), agent=_FakeAgent(), cron=_FakeCron(), deliver=_deliver)

    assert response == "important update"
    assert decisions == [True]
    assert len(delivered) == 1
    msg, record, session_key = delivered[0]
    assert msg.content == "important update"
    assert record is True
    assert session_key == "websocket:chat-1"


@pytest.mark.asyncio
async def test_bound_cron_silences_when_post_run_evaluator_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered: list[OutboundMessage] = []

    async def _reject(*_args: Any, default_notify: bool = False, **_kwargs: Any) -> bool:
        assert default_notify is True
        return False

    async def _deliver(
        msg: OutboundMessage,
        *,
        record: bool = False,
        session_key: str | None = None,
    ) -> None:
        delivered.append(msg)

    monkeypatch.setattr("nanobot.cron.bound_runner.evaluate_response", _reject)

    response = await run_bound_cron_job(_job(), agent=_FakeAgent(), cron=_FakeCron(), deliver=_deliver)

    assert response == "important update"
    assert delivered == []


@pytest.mark.asyncio
async def test_bound_cron_records_and_submits_session_turn() -> None:
    cron = _FakeCron()
    agent = _FakeAgent()

    response = await run_bound_cron_job(_job(), agent=agent, cron=cron)

    assert response == "important update"
    assert [record["status"] for _, record in cron.records] == ["queued", "ok"]
    assert len(agent.messages) == 1
    msg = agent.messages[0]
    assert msg.sender_id == "cron"
    assert msg.session_key_override == "websocket:chat-1"
    assert msg.metadata[CRON_TRIGGER_META]["job_id"] == "job-1"
