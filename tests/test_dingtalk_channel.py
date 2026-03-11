from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels import dingtalk as dt_mod
from nanobot.channels.dingtalk import DingTalkChannel, NanobotDingTalkHandler
from nanobot.channels.retry import ChannelHealth


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(client_id="cid", client_secret="secret", allow_from=[])


def _channel() -> DingTalkChannel:
    ch = object.__new__(DingTalkChannel)
    ch.config = _cfg()
    ch._running = False
    ch._client = None
    ch._http = None
    ch._access_token = None
    ch._token_expiry = 0
    ch._background_tasks = set()
    ch._handle_message = AsyncMock()
    ch._health = ChannelHealth()
    return ch


@pytest.mark.asyncio
async def test_start_validation_and_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _channel()

    monkeypatch.setattr(dt_mod, "DINGTALK_AVAILABLE", False)
    await ch.start()

    monkeypatch.setattr(dt_mod, "DINGTALK_AVAILABLE", True)
    ch.config.client_id = ""
    await ch.start()

    ch._http = SimpleNamespace(aclose=AsyncMock())
    t = AsyncMock()
    t.cancel = lambda: None
    ch._background_tasks.add(t)
    await ch.stop()
    assert ch._http is None


@pytest.mark.asyncio
async def test_token_send_and_on_message() -> None:
    ch = _channel()

    class _Resp:
        def __init__(self, code=200):
            self.status_code = code
            self.text = "err"

        def raise_for_status(self):
            return None

        def json(self):
            return {"accessToken": "tok", "expireIn": 100}

    ch._http = SimpleNamespace(post=AsyncMock(return_value=_Resp()))
    token = await ch._get_access_token()
    assert token == "tok"

    await ch.send(OutboundMessage(channel="dingtalk", chat_id="u1", content="hello"))
    assert ch._http.post.await_count >= 2

    await ch._on_message("hello", "u1", "Alice")
    assert ch._handle_message.await_count == 1


@pytest.mark.asyncio
async def test_handler_process_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _channel()
    handler = NanobotDingTalkHandler(ch)

    class _ChatMsg:
        TOPIC = "topic"

        def __init__(self, text="hello", mtype="text"):
            self.text = SimpleNamespace(content=text)
            self.message_type = mtype
            self.sender_staff_id = "u1"
            self.sender_id = "u1"
            self.sender_nick = "Alice"

        @staticmethod
        def from_dict(data):
            if data.get("kind") == "empty":
                return _ChatMsg(text="", mtype="unknown")
            return _ChatMsg(text=data.get("text", {}).get("content", "hello"))

    monkeypatch.setattr(dt_mod, "ChatbotMessage", _ChatMsg)
    monkeypatch.setattr(dt_mod, "AckMessage", SimpleNamespace(STATUS_OK="OK"))

    msg_empty = SimpleNamespace(data={"kind": "empty"})
    status, _ = await handler.process(msg_empty)
    assert status == "OK"

    msg_ok = SimpleNamespace(data={"text": {"content": "hello"}})
    status2, _ = await handler.process(msg_ok)
    assert status2 == "OK"
