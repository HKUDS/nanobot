from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.dingtalk import DingTalkChannel, NanobotDingTalkHandler
from nanobot.channels.mochat import (
    MochatBufferedEntry,
    build_buffered_body,
    extract_mention_ids,
    normalize_mochat_content,
    parse_timestamp,
    resolve_mochat_target,
    resolve_require_mention,
    resolve_was_mentioned,
    _make_synthetic_event,
    _safe_dict,
    _str_field,
)
from nanobot.channels.slack import SlackChannel
from nanobot.channels.telegram import TelegramChannel, _markdown_to_telegram_html, _split_message
from nanobot.channels.whatsapp import WhatsAppChannel
from nanobot.config.schema import (
    DingTalkConfig,
    MochatConfig,
    MochatGroupRule,
    MochatMentionConfig,
    SlackConfig,
    TelegramConfig,
    WhatsAppConfig,
)


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


def test_mochat_pure_helpers() -> None:
    assert _safe_dict({"x": 1}) == {"x": 1}
    assert _safe_dict("x") == {}
    assert _str_field({"a": "", "b": " y "}, "a", "b") == "y"

    ev = _make_synthetic_event("m1", "u1", {"x": 1}, {"k": 2}, "g", "c", author_info={"n": "z"})
    assert ev["payload"]["messageId"] == "m1"
    assert ev["payload"]["authorInfo"]["n"] == "z"

    assert normalize_mochat_content(" x ") == "x"
    assert normalize_mochat_content(None) == ""
    assert "k" in normalize_mochat_content({"k": 1})

    assert resolve_mochat_target("group:abc").is_panel is True
    assert resolve_mochat_target("session_1").is_panel is False
    assert resolve_mochat_target("").id == ""

    mentions = extract_mention_ids(["u1", {"id": "u2"}, {"userId": "u3"}, {"_id": "u4"}])
    assert mentions == ["u1", "u2", "u3", "u4"]
    assert extract_mention_ids("bad") == []

    payload = {"meta": {"mentioned": True}, "content": "hello"}
    assert resolve_was_mentioned(payload, "u1") is True
    payload2 = {"meta": {"mentionIds": ["u1"]}, "content": "hello"}
    assert resolve_was_mentioned(payload2, "u1") is True
    payload3 = {"meta": {}, "content": "@u1 ping"}
    assert resolve_was_mentioned(payload3, "u1") is True

    cfg = MochatConfig(
        mention=MochatMentionConfig(require_in_groups=False),
        groups={"g1": MochatGroupRule(require_mention=True)},
    )
    assert resolve_require_mention(cfg, session_id="s1", group_id="g1") is True
    assert resolve_require_mention(cfg, session_id="s1", group_id="none") is False

    one = [MochatBufferedEntry(raw_body="hello", author="u")]
    assert build_buffered_body(one, is_group=False) == "hello"
    many = [
        MochatBufferedEntry(raw_body="a", author="u1", sender_name="N1"),
        MochatBufferedEntry(raw_body="b", author="u2"),
    ]
    merged = build_buffered_body(many, is_group=True)
    assert "N1: a" in merged
    assert "u2: b" in merged
    assert parse_timestamp("2026-01-01T00:00:00Z") is not None
    assert parse_timestamp("bad") is None


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_whatsapp_send_paths() -> None:
    ch = WhatsAppChannel(WhatsAppConfig(), _Bus())
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
    assert sent and "\"to\": \"1\"" in sent[0]
    await ch.stop()


@pytest.mark.asyncio
async def test_dingtalk_access_token_and_send_paths() -> None:
    ch = DingTalkChannel(DingTalkConfig(client_id="cid", client_secret="sec"), _Bus())
    ch._access_token = "cached"
    ch._token_expiry = 9999999999
    assert await ch._get_access_token() == "cached"

    class _Resp:
        status_code = 200
        text = "ok"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"accessToken": "tok", "expireIn": 120}

    class _Http:
        async def post(self, *_args, **_kwargs):
            return _Resp()

        async def aclose(self) -> None:
            return None

    ch._http = _Http()
    ch._access_token = None
    assert await ch._get_access_token() == "tok"

    sent = {"n": 0}

    class _SendHttp(_Http):
        async def post(self, *_args, **_kwargs):
            sent["n"] += 1
            return _Resp()

    ch._http = _SendHttp()
    await ch.send(OutboundMessage(channel="dingtalk", chat_id="u1", content="hello"))
    assert sent["n"] >= 1


@pytest.mark.asyncio
async def test_dingtalk_handler_process_success(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = DingTalkChannel(DingTalkConfig(), _Bus())
    ch._on_message = AsyncMock()  # type: ignore[method-assign]

    class _Ack:
        STATUS_OK = "ok"

    class _Text:
        def __init__(self, content: str):
            self.content = content

    class _ChatMsg:
        message_type = "text"

        def __init__(self) -> None:
            self.text = _Text("hello")
            self.sender_staff_id = "u1"
            self.sender_id = "u1"
            self.sender_nick = "N"

        @staticmethod
        def from_dict(_data: dict[str, object]) -> "_ChatMsg":
            return _ChatMsg()

    monkeypatch.setattr("nanobot.channels.dingtalk.AckMessage", _Ack)
    monkeypatch.setattr("nanobot.channels.dingtalk.ChatbotMessage", _ChatMsg)

    handler = NanobotDingTalkHandler(ch)
    status, _msg = await handler.process(SimpleNamespace(data={"text": {"content": "hello"}}))
    assert status == "ok"

    # Give background task time to run.
    await asyncio.sleep(0)
    assert ch._on_message.await_count == 1
