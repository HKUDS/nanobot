import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.session_delivery import origin_delivery_context
from nanobot.cron.session_turns import CRON_TRIGGER_META
from nanobot.cron.types import CronJob, CronPayload


def test_origin_delivery_context_uses_explicit_origin_fields() -> None:
    metadata = {
        "context_chat_id": "456",
        "parent_channel_id": "456",
        "thread_id": "777",
    }
    job = CronJob(
        id="thread-check",
        name="Thread check",
        payload=CronPayload(
            message="check",
            session_key="discord:456:thread:777",
            origin_channel="discord",
            origin_chat_id="777",
            origin_metadata=metadata,
        ),
    )

    channel, chat_id, returned_metadata = origin_delivery_context(job)

    assert channel == "discord"
    assert chat_id == "777"
    assert returned_metadata == metadata
    assert returned_metadata is not metadata


def test_origin_delivery_context_rejects_missing_origin_fields() -> None:
    job = CronJob(
        id="old-bound",
        name="Old bound job",
        payload=CronPayload(
            message="check",
            session_key="websocket:chat-1",
        ),
    )

    with pytest.raises(ValueError, match="missing origin delivery context"):
        origin_delivery_context(job)


@pytest.mark.asyncio
async def test_bound_cron_job_forwards_model_preset_metadata() -> None:
    seen = {}

    class Agent:
        tools = {}

        async def submit_cron_turn(self, msg):
            seen["msg"] = msg
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="ok")

    class Cron:
        def __init__(self) -> None:
            self.records = []

        def write_run_record(self, run_id, record):
            self.records.append(record)

    cron = Cron()
    job = CronJob(
        id="preset-job",
        name="Preset job",
        payload=CronPayload(
            message="check",
            session_key="websocket:chat-1",
            origin_channel="websocket",
            origin_chat_id="chat-1",
            model_preset="fast",
        ),
    )

    response = await run_bound_cron_job(job, agent=Agent(), cron=cron)

    assert response == "ok"
    msg = seen["msg"]
    assert msg.metadata["model_preset"] == "fast"
    assert msg.metadata[CRON_TRIGGER_META]["model_preset"] == "fast"
    assert any(record.get("model_preset") == "fast" for record in cron.records)


@pytest.mark.asyncio
async def test_bound_cron_job_records_model_preset_errors() -> None:
    class Agent:
        tools = {}

        async def submit_cron_turn(self, _msg):
            raise ValueError("cron model_preset 'deleted' is not configured")

    class Cron:
        def __init__(self) -> None:
            self.records = []

        def write_run_record(self, run_id, record):
            self.records.append(record)

    cron = Cron()
    job = CronJob(
        id="preset-job",
        name="Preset job",
        payload=CronPayload(
            message="check",
            session_key="websocket:chat-1",
            origin_channel="websocket",
            origin_chat_id="chat-1",
            model_preset="deleted",
        ),
    )

    with pytest.raises(ValueError, match="cron model_preset 'deleted' is not configured"):
        await run_bound_cron_job(job, agent=Agent(), cron=cron)

    assert cron.records[-1]["status"] == "error"
    assert cron.records[-1]["model_preset"] == "deleted"
    assert cron.records[-1]["error"] == "cron model_preset 'deleted' is not configured"
