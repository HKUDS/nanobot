from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TelegramChannel
from nanobot.config.schema import TelegramConfig


class _FakeHTTPXRequest:
    instances: list["_FakeHTTPXRequest"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.__class__.instances.append(self)


class _FakeUpdater:
    def __init__(self, on_start_polling) -> None:
        self._on_start_polling = on_start_polling

    async def start_polling(self, **kwargs) -> None:
        self._on_start_polling()


class _FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []

    async def get_me(self):
        return SimpleNamespace(username="nanobot_test")

    async def set_my_commands(self, commands) -> None:
        self.commands = commands

    async def send_message(self, **kwargs) -> None:
        self.sent_messages.append(kwargs)


class _FakeApp:
    def __init__(self, on_start_polling) -> None:
        self.bot = _FakeBot()
        self.updater = _FakeUpdater(on_start_polling)
        self.handlers = []
        self.error_handlers = []

    def add_error_handler(self, handler) -> None:
        self.error_handlers.append(handler)

    def add_handler(self, handler) -> None:
        self.handlers.append(handler)

    async def initialize(self) -> None:
        pass

    async def start(self) -> None:
        pass


class _FakeBuilder:
    def __init__(self, app: _FakeApp) -> None:
        self.app = app
        self.token_value = None
        self.request_value = None
        self.get_updates_request_value = None

    def token(self, token: str):
        self.token_value = token
        return self

    def request(self, request):
        self.request_value = request
        return self

    def get_updates_request(self, request):
        self.get_updates_request_value = request
        return self

    def proxy(self, _proxy):
        raise AssertionError("builder.proxy should not be called when request is set")

    def get_updates_proxy(self, _proxy):
        raise AssertionError("builder.get_updates_proxy should not be called when request is set")

    def build(self):
        return self.app


@pytest.mark.asyncio
async def test_start_uses_request_proxy_without_builder_proxy(monkeypatch) -> None:
    config = TelegramConfig(
        enabled=True,
        token="123:abc",
        allow_from=["*"],
        proxy="http://127.0.0.1:7890",
    )
    bus = MessageBus()
    channel = TelegramChannel(config, bus)
    app = _FakeApp(lambda: setattr(channel, "_running", False))
    builder = _FakeBuilder(app)

    monkeypatch.setattr("nanobot.channels.telegram.HTTPXRequest", _FakeHTTPXRequest)
    monkeypatch.setattr(
        "nanobot.channels.telegram.Application",
        SimpleNamespace(builder=lambda: builder),
    )

    await channel.start()

    assert len(_FakeHTTPXRequest.instances) == 1
    assert _FakeHTTPXRequest.instances[0].kwargs["proxy"] == config.proxy
    assert builder.request_value is _FakeHTTPXRequest.instances[0]
    assert builder.get_updates_request_value is _FakeHTTPXRequest.instances[0]


def test_derive_topic_session_key_uses_thread_id() -> None:
    message = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup"),
        chat_id=-100123,
        message_thread_id=42,
    )

    assert TelegramChannel._derive_topic_session_key(message) == "telegram:-100123:topic:42"


def test_get_extension_falls_back_to_original_filename() -> None:
    channel = TelegramChannel(TelegramConfig(), MessageBus())

    assert channel._get_extension("file", None, "report.pdf") == ".pdf"
    assert channel._get_extension("file", None, "archive.tar.gz") == ".tar.gz"


def test_is_allowed_accepts_legacy_telegram_id_username_formats() -> None:
    channel = TelegramChannel(TelegramConfig(allow_from=["12345", "alice", "67890|bob"]), MessageBus())

    assert channel.is_allowed("12345|carol") is True
    assert channel.is_allowed("99999|alice") is True
    assert channel.is_allowed("67890|bob") is True


def test_is_allowed_rejects_invalid_legacy_telegram_sender_shapes() -> None:
    channel = TelegramChannel(TelegramConfig(allow_from=["alice"]), MessageBus())

    assert channel.is_allowed("attacker|alice|extra") is False
    assert channel.is_allowed("not-a-number|alice") is False


@pytest.mark.asyncio
async def test_send_progress_keeps_message_in_topic() -> None:
    config = TelegramConfig(enabled=True, token="123:abc", allow_from=["*"])
    channel = TelegramChannel(config, MessageBus())
    channel._app = _FakeApp(lambda: None)

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="hello",
            metadata={"_progress": True, "message_thread_id": 42},
        )
    )

    assert channel._app.bot.sent_messages[0]["message_thread_id"] == 42


@pytest.mark.asyncio
async def test_send_reply_infers_topic_from_message_id_cache() -> None:
    config = TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], reply_to_message=True)
    channel = TelegramChannel(config, MessageBus())
    channel._app = _FakeApp(lambda: None)
    channel._message_threads[("123", 10)] = 42

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="hello",
            metadata={"message_id": 10},
        )
    )

    assert channel._app.bot.sent_messages[0]["message_thread_id"] == 42
    assert channel._app.bot.sent_messages[0]["reply_parameters"].message_id == 10


@pytest.mark.asyncio
async def test_telegram_media_uses_file_unique_id_for_storage(tmp_path: Path) -> None:
    config = TelegramConfig(enabled=True, token="test", allow_from=["*"])
    channel = TelegramChannel(config, MessageBus())

    download = AsyncMock()
    channel._app = SimpleNamespace(
        bot=SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(download_to_drive=download))
        )
    )

    photo = SimpleNamespace(
        file_id="very-long-telegram-file-id-1234567890",
        file_unique_id="stable-unique-id-42",
        mime_type="image/jpeg",
    )
    user = SimpleNamespace(id=123, username="alice", first_name="Alice")
    message = SimpleNamespace(
        text=None,
        caption=None,
        photo=[photo],
        voice=None,
        audio=None,
        document=None,
        chat_id=456,
        chat=SimpleNamespace(type="private"),
        message_id=789,
        media_group_id=None,
    )
    update = SimpleNamespace(message=message, effective_user=user)

    with patch("pathlib.Path.home", return_value=tmp_path):
        await channel._on_message(update, None)

    expected_path = tmp_path / ".nanobot" / "media" / "stable-unique-id-42.jpg"
    download.assert_awaited_once_with(str(expected_path))

    inbound = await channel.bus.consume_inbound()
    assert inbound.media == [str(expected_path)]
    assert str(expected_path) in inbound.content


@pytest.mark.asyncio
async def test_telegram_media_falls_back_to_file_id_when_unique_id_missing(tmp_path: Path) -> None:
    config = TelegramConfig(enabled=True, token="test", allow_from=["*"])
    channel = TelegramChannel(config, MessageBus())

    download = AsyncMock()
    channel._app = SimpleNamespace(
        bot=SimpleNamespace(
            get_file=AsyncMock(return_value=SimpleNamespace(download_to_drive=download))
        )
    )

    document = SimpleNamespace(
        file_id="full-file-id-abcdef1234567890",
        mime_type="application/pdf",
    )
    user = SimpleNamespace(id=123, username=None, first_name="Alice")
    message = SimpleNamespace(
        text=None,
        caption=None,
        photo=None,
        voice=None,
        audio=None,
        document=document,
        chat_id=456,
        chat=SimpleNamespace(type="private"),
        message_id=790,
        media_group_id=None,
    )
    update = SimpleNamespace(message=message, effective_user=user)

    with patch("pathlib.Path.home", return_value=tmp_path):
        await channel._on_message(update, None)

    expected_path = tmp_path / ".nanobot" / "media" / "full-file-id-abcdef1234567890"
    download.assert_awaited_once_with(str(expected_path))

    inbound = await channel.bus.consume_inbound()
    assert inbound.media == [str(expected_path)]
    assert str(expected_path) in inbound.content
