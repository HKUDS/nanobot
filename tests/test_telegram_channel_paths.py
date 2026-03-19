from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.retry import ChannelHealth
from nanobot.channels.telegram import TelegramChannel
from nanobot.errors import DeliverySkippedError


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(token="token", proxy=None, reply_to_message=True, allow_from=[])


def _channel() -> TelegramChannel:
    ch = object.__new__(TelegramChannel)
    ch.config = _cfg()
    ch.groq_api_key = ""
    ch._running = False
    ch._app = None
    ch._chat_ids = {}
    ch._typing_tasks = {}
    ch._streaming_msg_ids = {}
    ch._handle_message = AsyncMock()
    ch._health = ChannelHealth()
    return ch


async def test_start_validation_and_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = _channel()
    ch.config.token = ""
    await ch.start()

    bot = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="bot")),
        set_my_commands=AsyncMock(),
    )
    updater = SimpleNamespace(start_polling=AsyncMock(), stop=AsyncMock())

    class _App:
        def __init__(self):
            self.bot = bot
            self.updater = updater

        def add_error_handler(self, _fn):
            return None

        def add_handler(self, _h):
            return None

        async def initialize(self):
            return None

        async def start(self):
            return None

        async def stop(self):
            return None

        async def shutdown(self):
            return None

    class _Builder:
        def token(self, _v):
            return self

        def request(self, _v):
            return self

        def get_updates_request(self, _v):
            return self

        def proxy(self, _v):
            return self

        def get_updates_proxy(self, _v):
            return self

        def build(self):
            return _App()

    monkeypatch.setattr(
        "nanobot.channels.telegram.Application", SimpleNamespace(builder=lambda: _Builder())
    )
    monkeypatch.setattr("nanobot.channels.telegram.HTTPXRequest", lambda **kwargs: object())

    original_sleep = asyncio.sleep

    async def _sleep_once(_s: float):
        ch._running = False
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sleep_once)
    ch.config.token = "token"
    await ch.start()

    ch._typing_tasks["1"] = asyncio.create_task(original_sleep(0.01))
    await ch.stop()
    assert ch._app is None


async def test_send_and_streaming_and_helpers(tmp_path: Path) -> None:
    ch = _channel()

    class _Bot:
        def __init__(self):
            self.send_message = AsyncMock(return_value=SimpleNamespace(message_id=7))
            self.send_photo = AsyncMock()
            self.send_voice = AsyncMock()
            self.send_audio = AsyncMock()
            self.send_document = AsyncMock()
            self.edit_message_text = AsyncMock(side_effect=Exception("not modified"))
            self.send_chat_action = AsyncMock(side_effect=Exception("stop"))

    bot = _Bot()
    ch._app = SimpleNamespace(bot=bot)

    with pytest.raises(DeliverySkippedError):
        await ch.send(OutboundMessage(channel="telegram", chat_id="bad", content="hello"))

    media = tmp_path / "x.jpg"
    media.write_bytes(b"data")
    msg = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content="hello",
        media=[str(media)],
        metadata={"message_id": 1},
    )
    await ch.send(msg)
    assert bot.send_photo.await_count == 1

    stream = OutboundMessage(
        channel="telegram",
        chat_id="123",
        content="chunk",
        metadata={"_streaming": True, "_progress": True},
    )
    await ch.send(stream)

    ch._start_typing("123")
    await asyncio.sleep(0)
    ch._stop_typing("123")

    assert ch._get_media_type("a.mp3") == "audio"
    assert ch._get_extension("voice", "audio/ogg") == ".ogg"
    assert ch._sender_id(SimpleNamespace(id=1, username="u")) == "1|u"


async def test_acl_blocks_media_download_for_unauthorized_user(tmp_path: Path) -> None:
    """T-H2 (LAN-38): ACL check must happen before any media download."""
    ch = _channel()
    # Allow only user 999; sender will be user 1 — unauthorized
    ch.config.allow_from = ["999"]

    class _File:
        async def download_to_drive(self, path: str):
            Path(path).write_text("x", encoding="utf-8")

    bot = SimpleNamespace(get_file=AsyncMock(return_value=_File()))
    ch._app = SimpleNamespace(bot=bot)
    ch._start_typing = lambda _chat: None  # type: ignore[method-assign]

    user = SimpleNamespace(id=1, username="u", first_name="U")
    photo_stub = SimpleNamespace(file_id="photo-id", width=800, height=600)
    msg = SimpleNamespace(
        chat_id=42,
        text="",
        caption="",
        photo=[photo_stub],
        voice=None,
        audio=None,
        document=None,
        message_id=9,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    upd = SimpleNamespace(message=msg, effective_user=user)

    await ch._on_message(upd, None)

    # The unauthorized sender must not trigger any file download
    bot.get_file.assert_not_called()
    # And the message must not reach the agent
    ch._handle_message.assert_not_called()


async def test_message_and_command_handlers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ch = _channel()

    class _File:
        async def download_to_drive(self, path: str):
            Path(path).write_text("x", encoding="utf-8")

    bot = SimpleNamespace(get_file=AsyncMock(return_value=_File()))
    ch._app = SimpleNamespace(bot=bot)
    ch._start_typing = lambda _chat: None  # type: ignore[method-assign]

    user = SimpleNamespace(id=1, username="u", first_name="U")
    msg = SimpleNamespace(
        chat_id=42,
        text="hello",
        caption="",
        photo=[],
        voice=None,
        audio=None,
        document=None,
        message_id=9,
        chat=SimpleNamespace(type="private"),
        reply_text=AsyncMock(),
    )
    upd = SimpleNamespace(message=msg, effective_user=user)

    await ch._on_start(upd, None)
    await ch._on_help(upd, None)
    await ch._forward_command(
        SimpleNamespace(message=SimpleNamespace(chat_id=42, text="/new"), effective_user=user), None
    )
    await ch._on_message(upd, None)

    assert ch._handle_message.await_count >= 2
