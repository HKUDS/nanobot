from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.channels.mochat import (
    MochatBufferedEntry,
    MochatChannel,
    build_buffered_body,
    extract_mention_ids,
    normalize_mochat_content,
    parse_timestamp,
    resolve_mochat_target,
    resolve_require_mention,
    resolve_was_mentioned,
)
from nanobot.channels.retry import ChannelHealth


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        agent_user_id="agent-1",
        groups={
            "g1": SimpleNamespace(require_mention=True),
            "*": SimpleNamespace(require_mention=False),
        },
        mention=SimpleNamespace(require_in_groups=True),
        reply_delay_mode="none",
        watch_limit=50,
        claw_token="token",
        allow_from=[],
    )


def _channel() -> MochatChannel:
    ch = object.__new__(MochatChannel)
    ch.config = _cfg()
    ch._panel_set = {"panel-1"}
    ch._session_set = set()
    ch._session_cursor = {}
    ch._cursor_save_task = None
    ch._cold_sessions = set()
    ch._target_locks = {}
    ch._remember_message_id = lambda key, mid: False
    ch._handle_message = AsyncMock()
    ch._enqueue_delayed_entry = AsyncMock()
    ch._flush_delayed_entries = AsyncMock()
    ch._dispatch_entries = AsyncMock()
    ch._api_send = AsyncMock(return_value={"ok": True})
    ch._health = ChannelHealth()
    return ch


def test_pure_helpers_target_mentions_and_content() -> None:
    assert resolve_mochat_target("session_1").is_panel is False
    assert resolve_mochat_target("panel:abc").is_panel is True
    assert resolve_mochat_target("group:xyz").id == "xyz"

    ids = extract_mention_ids(["u1", {"userId": "u2"}, {"id": "u3"}, {"_id": "u4"}])
    assert ids == ["u1", "u2", "u3", "u4"]

    payload = {"meta": {"mentioned": True}, "content": "no"}
    assert resolve_was_mentioned(payload, "agent-1") is True
    payload2 = {"meta": {"mentions": [{"id": "agent-1"}]}, "content": "no"}
    assert resolve_was_mentioned(payload2, "agent-1") is True
    payload3 = {"meta": {}, "content": "hello @agent-1"}
    assert resolve_was_mentioned(payload3, "agent-1") is True

    assert resolve_require_mention(_cfg(), "s1", "g1") is True

    entries = [
        MochatBufferedEntry(raw_body="hello", author="u1", sender_name="Alice", group_id="g1"),
        MochatBufferedEntry(raw_body="world", author="u2", sender_username="bob", group_id="g1"),
    ]
    assert build_buffered_body(entries, is_group=True) == "Alice: hello\nbob: world"
    assert normalize_mochat_content({"x": 1}) == '{"x": 1}'
    assert parse_timestamp("not-a-time") is None


@pytest.mark.asyncio
async def test_build_notify_handler_routes_events() -> None:
    ch = _channel()
    ch._handle_notify_inbox_append = AsyncMock()
    ch._handle_notify_chat_message = AsyncMock()

    h1 = ch._build_notify_handler("notify:chat.inbox.append")
    h2 = ch._build_notify_handler("notify:chat.message.add")

    await h1({"x": 1})
    await h2({"y": 2})

    assert ch._handle_notify_inbox_append.await_count == 1
    assert ch._handle_notify_chat_message.await_count == 1


@pytest.mark.asyncio
async def test_subscribe_sessions_handles_ack_shapes() -> None:
    ch = _channel()
    ch._handle_watch_payload = AsyncMock()

    async def _socket_ok(_event: str, _payload: dict):
        return {"result": True, "data": {"sessions": [{"sessionId": "s1", "events": []}]}}

    ch._socket_call = _socket_ok  # type: ignore[method-assign]
    ok = await ch._subscribe_sessions(["s1"])
    assert ok is True
    assert ch._handle_watch_payload.await_count == 1

    async def _socket_fail(_event: str, _payload: dict):
        return {"result": False, "message": "nope"}

    ch._socket_call = _socket_fail  # type: ignore[method-assign]
    ok2 = await ch._subscribe_sessions(["s2"])
    assert ok2 is False


@pytest.mark.asyncio
async def test_handle_watch_payload_cold_session_and_dispatch() -> None:
    ch = _channel()
    ch._process_inbound_event = AsyncMock()
    ch._cold_sessions = {"s1"}

    await ch._handle_watch_payload(
        {
            "sessionId": "s1",
            "cursor": 10,
            "events": [{"type": "message.add", "seq": 11, "payload": {}}],
        },
        "session",
    )
    assert ch._process_inbound_event.await_count == 0

    await ch._handle_watch_payload(
        {
            "sessionId": "s1",
            "cursor": 12,
            "events": [
                {"type": "message.add", "seq": 13, "payload": {"author": "u1", "messageId": "m1"}}
            ],
        },
        "session",
    )
    assert ch._process_inbound_event.await_count == 1
    assert ch._session_cursor["s1"] == 13


@pytest.mark.asyncio
async def test_send_routes_to_panel_or_session_and_skips_empty() -> None:
    ch = _channel()

    msg_panel = SimpleNamespace(
        content="hello",
        media=["https://x"],
        chat_id="panel:panel-1",
        reply_to="r1",
        metadata={"group_id": "g1"},
    )
    await ch.send(msg_panel)
    assert ch._api_send.await_count == 1

    msg_session = SimpleNamespace(
        content=" ", media=[], chat_id="session_1", reply_to=None, metadata={}
    )
    await ch.send(msg_session)
    assert ch._api_send.await_count == 1
