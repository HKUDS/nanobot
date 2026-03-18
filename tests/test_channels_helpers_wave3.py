from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.slack import SlackChannel
from nanobot.channels.telegram import TelegramChannel, _markdown_to_telegram_html, _split_message
from nanobot.channels.whatsapp import WhatsAppChannel
from nanobot.config.schema import (
    SlackConfig,
    WhatsAppConfig,
)
from nanobot.errors import DeliverySkippedError


class _Bus:
    async def publish_inbound(self, _msg) -> None:
        return None


def test_telegram_markdown_and_split_helpers() -> None:
    html = _markdown_to_telegram_html(
        "# T\n**b** _i_ ~~s~~ [l](https://e.x)\n- item\n`x<y`\n```\na&b\n```"
    )
    assert "<b>b</b>" in html
    assert "<i>i</i>" in html
    assert "<s>s</s>" in html
    assert '<a href="https://e.x">l</a>' in html
    assert "• item" in html
    assert "<code>x&lt;y</code>" in html
    assert "<pre><code>a&amp;b" in html
    assert _markdown_to_telegram_html("") == ""

    chunks = _split_message("a b c d", max_len=3)
    assert len(chunks) >= 2
    assert _split_message("short", max_len=20) == ["short"]


def test_telegram_media_type_helper() -> None:
    assert TelegramChannel._get_media_type("x.jpg") == "photo"
    assert TelegramChannel._get_media_type("x.ogg") == "voice"
    assert TelegramChannel._get_media_type("x.mp3") == "audio"
    assert TelegramChannel._get_media_type("x.bin") == "document"


def test_slack_policy_and_markdown_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = SlackConfig()
    ch = SlackChannel(cfg, _Bus())
    ch._bot_user_id = "U123"

    assert ch._is_allowed("u1", "c1", "im") is True
    cfg.dm.policy = "allowlist"
    cfg.dm.allow_from = ["u1"]
    assert ch._is_allowed("u1", "c1", "im") is True
    assert ch._is_allowed("u2", "c1", "im") is False

    cfg.group_policy = "open"
    assert ch._should_respond_in_channel("message", "hi", "C") is True
    cfg.group_policy = "mention"
    assert ch._should_respond_in_channel("app_mention", "hi", "C") is True
    assert ch._should_respond_in_channel("message", "<@U123> hi", "C") is True
    cfg.group_policy = "allowlist"
    cfg.group_allow_from = ["C1"]
    assert ch._should_respond_in_channel("message", "x", "C1") is True
    assert ch._should_respond_in_channel("message", "x", "C2") is False

    assert ch._strip_bot_mention("<@U123>  hello") == "hello"

    monkeypatch.setattr("nanobot.channels.slack.slackify_markdown", lambda t: t)
    table = "| A | B |\n|---|---|\n| 1 | 2 |"
    mrk = ch._to_mrkdwn(table)
    assert "*A*: 1" in mrk

    fixed = ch._fixup_mrkdwn("**x**\n# h\nhttps://e.x?a=1&amp;b=2\n`c`")
    assert "*x*" in fixed
    assert "*h*" in fixed
    assert "&amp;" not in fixed


async def test_whatsapp_bridge_message_paths() -> None:
    ch = WhatsAppChannel(WhatsAppConfig(), _Bus())
    ch._handle_message = AsyncMock()  # type: ignore[method-assign]

    await ch._handle_bridge_message("{bad")
    await ch._handle_bridge_message(json.dumps({"type": "status", "status": "connected"}))
    assert ch._connected is True
    await ch._handle_bridge_message(json.dumps({"type": "status", "status": "disconnected"}))
    assert ch._connected is False

    await ch._handle_bridge_message(
        json.dumps(
            {
                "type": "message",
                "pn": "123@s.whatsapp.net",
                "sender": "lid_1@lid",
                "content": "[Voice Message]",
                "id": "m1",
            }
        )
    )
    assert ch._handle_message.await_count == 1


async def test_whatsapp_send_paths() -> None:
    ch = WhatsAppChannel(WhatsAppConfig(), _Bus())
    with pytest.raises(DeliverySkippedError):
        await ch.send(OutboundMessage(channel="whatsapp", chat_id="a", content="x"))

    sent: list[str] = []

    class _WS:
        async def send(self, payload: str) -> None:
            sent.append(payload)

        async def close(self) -> None:
            return None

    ch._ws = _WS()
    ch._connected = True
    await ch.send(OutboundMessage(channel="whatsapp", chat_id="1", content="hi"))
    assert sent and '"to": "1"' in sent[0]
    await ch.stop()
