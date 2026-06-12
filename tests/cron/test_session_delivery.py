import pytest

from nanobot.cron.session_delivery import origin_delivery_context
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
