import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.mochat import (
    MochatBufferedEntry,
    MochatChannel,
    build_buffered_body,
    resolve_mochat_target,
    resolve_require_mention,
    resolve_was_mentioned,
)
from nanobot.config.schema import MochatConfig, MochatGroupRule, MochatMentionConfig


def test_resolve_mochat_target_prefixes() -> None:
    t = resolve_mochat_target("panel:abc")
    assert t.id == "abc"
    assert t.is_panel is True

    t = resolve_mochat_target("session_123")
    assert t.id == "session_123"
    assert t.is_panel is False

    t = resolve_mochat_target("mochat:session_456")
    assert t.id == "session_456"
    assert t.is_panel is False


def test_resolve_was_mentioned_from_meta_and_text() -> None:
    payload = {
        "content": "hello",
        "meta": {
            "mentionIds": ["bot-1"],
        },
    }
    assert resolve_was_mentioned(payload, "bot-1") is True

    payload = {"content": "ping <@bot-2>", "meta": {}}
    assert resolve_was_mentioned(payload, "bot-2") is True


def test_resolve_require_mention_priority() -> None:
    cfg = MochatConfig(
        groups={
            "*": MochatGroupRule(require_mention=False),
            "group-a": MochatGroupRule(require_mention=True),
        },
        mention=MochatMentionConfig(require_in_groups=False),
    )

    assert resolve_require_mention(cfg, session_id="panel-x", group_id="group-a") is True
    assert resolve_require_mention(cfg, session_id="panel-x", group_id="group-b") is False


@pytest.mark.asyncio
async def test_delay_buffer_flushes_on_mention() -> None:
    bus = MessageBus()
    cfg = MochatConfig(
        enabled=True,
        claw_token="token",
        agent_user_id="bot",
        reply_delay_mode="non-mention",
        reply_delay_ms=60_000,
    )
    channel = MochatChannel(cfg, bus)

    first = {
        "type": "message.add",
        "timestamp": "2026-02-07T10:00:00Z",
        "payload": {
            "messageId": "m1",
            "author": "user1",
            "content": "first",
            "groupId": "group-1",
            "meta": {},
        },
    }
    second = {
        "type": "message.add",
        "timestamp": "2026-02-07T10:00:01Z",
        "payload": {
            "messageId": "m2",
            "author": "user2",
            "content": "hello <@bot>",
            "groupId": "group-1",
            "meta": {},
        },
    }

    await channel._process_inbound_event(target_id="panel-1", event=first, target_kind="panel")
    assert bus.inbound_size == 0

    await channel._process_inbound_event(target_id="panel-1", event=second, target_kind="panel")
    assert bus.inbound_size == 1

    msg = await bus.consume_inbound()
    assert msg.channel == "mochat"
    assert msg.chat_id == "panel-1"
    assert "user1: first" in msg.content
    assert "user2: hello <@bot>" in msg.content
    assert msg.metadata.get("buffered_count") == 2

    await channel._cancel_delay_timers()


def test_build_buffered_body_group_labels() -> None:
    body = build_buffered_body(
        entries=[
            MochatBufferedEntry(raw_body="a", author="u1", sender_name="Alice"),
            MochatBufferedEntry(raw_body="b", author="u2", sender_username="bot"),
        ],
        is_group=True,
    )
    assert "Alice: a" in body
    assert "bot: b" in body
