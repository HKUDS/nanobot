from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.slack import SlackChannel


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        bot_token="xoxb",
        app_token="xapp",
        mode="socket",
        dm=SimpleNamespace(enabled=True, policy="open", allow_from=[]),
        group_policy="mention",
        group_allow_from=["C1"],
        reply_in_thread=True,
        react_emoji="eyes",
    )


def _channel() -> SlackChannel:
    ch = object.__new__(SlackChannel)
    ch.config = _cfg()
    ch._running = False
    ch._web_client = None
    ch._socket_client = None
    ch._bot_user_id = "B123"
    ch._handle_message = AsyncMock()
    return ch


@pytest.mark.asyncio
async def test_start_validation_and_stop() -> None:
    ch = _channel()
    ch.config.bot_token = ""
    await ch.start()

    ch.config.bot_token = "x"
    ch.config.mode = "invalid"
    await ch.start()

    ch._socket_client = SimpleNamespace(close=AsyncMock())
    await ch.stop()
    assert ch._socket_client is None


@pytest.mark.asyncio
async def test_send_paths() -> None:
    ch = _channel()
    ch._web_client = SimpleNamespace(
        chat_postMessage=AsyncMock(),
        files_upload_v2=AsyncMock(side_effect=[RuntimeError("upload-fail"), None]),
    )

    msg = OutboundMessage(
        channel="slack",
        chat_id="C1",
        content="hello",
        media=["/tmp/a.txt", "/tmp/b.txt"],
        metadata={"slack": {"thread_ts": "111.1", "channel_type": "channel"}},
    )
    await ch.send(msg)
    assert ch._web_client.chat_postMessage.await_count == 1
    assert ch._web_client.files_upload_v2.await_count == 2


@pytest.mark.asyncio
async def test_socket_request_filters_and_dispatch() -> None:
    ch = _channel()
    ch._web_client = SimpleNamespace(reactions_add=AsyncMock())

    client = SimpleNamespace(send_socket_mode_response=AsyncMock())

    req_other = SimpleNamespace(type="hello", envelope_id="e1", payload={})
    await ch._on_socket_request(client, req_other)

    req_no_event = SimpleNamespace(type="events_api", envelope_id="e2", payload={"event": {"type": "member_joined_channel"}})
    await ch._on_socket_request(client, req_no_event)

    mention_event = {
        "type": "app_mention",
        "user": "U1",
        "channel": "C1",
        "text": "<@B123> hi",
        "ts": "222.2",
        "channel_type": "channel",
    }
    req_ok = SimpleNamespace(type="events_api", envelope_id="e3", payload={"event": mention_event})
    await ch._on_socket_request(client, req_ok)

    assert ch._handle_message.await_count == 1
    assert ch._web_client.reactions_add.await_count == 1


def test_slack_helpers() -> None:
    ch = _channel()

    assert ch._is_allowed("U1", "C1", "im") is True
    ch.config.dm.policy = "allowlist"
    ch.config.dm.allow_from = ["U2"]
    assert ch._is_allowed("U1", "C1", "im") is False

    ch.config.group_policy = "open"
    assert ch._should_respond_in_channel("message", "hello", "C1") is True
    ch.config.group_policy = "mention"
    assert ch._should_respond_in_channel("app_mention", "hello", "C1") is True
    assert ch._should_respond_in_channel("message", "<@B123> hi", "C1") is True

    assert ch._strip_bot_mention("<@B123> hello") == "hello"

    md = "| A | B |\n|---|---|\n| 1 | 2 |\n\n**bold**"
    out = ch._to_mrkdwn(md)
    assert "A" in out and "B" in out
