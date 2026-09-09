import pytest

from nanobot.cron.session_delivery import configured_delivery_context, origin_delivery_context
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


def test_configured_delivery_context_falls_back_to_origin() -> None:
    job = CronJob(
        id="job1",
        name="health",
        payload=CronPayload(
            session_key="websocket:topic-1",
            origin_channel="websocket",
            origin_chat_id="topic-1",
            origin_metadata={"webui": True},
        ),
    )

    assert configured_delivery_context(job) == (
        "websocket",
        "topic-1",
        {"webui": True},
    )


def test_configured_delivery_context_uses_explicit_target_without_origin_metadata() -> None:
    job = CronJob(
        id="job1",
        name="health",
        payload=CronPayload(
            session_key="websocket:topic-1",
            origin_channel="websocket",
            origin_chat_id="topic-1",
            origin_metadata={"webui": True},
            delivery_channel="slack",
            delivery_chat_id="C123",
            delivery_metadata={"thread_ts": "123.456"},
        ),
    )

    assert configured_delivery_context(job) == (
        "slack",
        "C123",
        {"thread_ts": "123.456"},
    )


@pytest.mark.parametrize(
    ("delivery_channel", "delivery_chat_id"),
    [("slack", None), (None, "C123"), ("", "C123"), ("slack", "")],
)
def test_configured_delivery_context_rejects_partial_target(
    delivery_channel: str | None,
    delivery_chat_id: str | None,
) -> None:
    job = CronJob(
        id="job1",
        name="health",
        payload=CronPayload(
            session_key="websocket:topic-1",
            origin_channel="websocket",
            origin_chat_id="topic-1",
            delivery_channel=delivery_channel,
            delivery_chat_id=delivery_chat_id,
        ),
    )

    with pytest.raises(ValueError, match="incomplete delivery target"):
        configured_delivery_context(job)
