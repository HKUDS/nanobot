import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Check optional Telegram dependencies before running tests
try:
    import telegram  # noqa: F401
except ImportError:
    pytest.skip("Telegram dependencies not installed (python-telegram-bot)", allow_module_level=True)

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TELEGRAM_REPLY_CONTEXT_MAX_LEN, TelegramChannel, _StreamBuf
from nanobot.channels.telegram import TelegramConfig


class _FakeHTTPXRequest:
    instances: list["_FakeHTTPXRequest"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    @classmethod
    def clear(cls) -> None:
        cls.instances.clear()


class _FakeUpdater:
    def __init__(self, on_start_polling) -> None:
        self._on_start_polling = on_start_polling

    async def start_polling(self, **kwargs) -> None:
        self._on_start_polling()


class _FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.sent_media: list[dict] = []
        self.get_me_calls = 0

    async def get_me(self):
        self.get_me_calls += 1
        return SimpleNamespace(id=999, username="nanobot_test")

    async def set_my_commands(self, commands) -> None:
        self.commands = commands

    async def send_message(self, **kwargs):
        self.sent_messages.append(kwargs)
        return SimpleNamespace(message_id=len(self.sent_messages))

    async def send_photo(self, **kwargs) -> None:
        self.sent_media.append({"kind": "photo", **kwargs})

    async def send_voice(self, **kwargs) -> None:
        self.sent_media.append({"kind": "voice", **kwargs})

    async def send_audio(self, **kwargs) -> None:
        self.sent_media.append({"kind": "audio", **kwargs})

    async def send_document(self, **kwargs) -> None:
        self.sent_media.append({"kind": "document", **kwargs})

    async def send_chat_action(self, **kwargs) -> None:
        pass

    async def get_file(self, file_id: str):
        """Return a fake file that 'downloads' to a path (for reply-to-media tests)."""
        async def _fake_download(path) -> None:
            pass
        return SimpleNamespace(download_to_drive=_fake_download)


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


def _make_telegram_update(
    *,
    chat_type: str = "group",
    text: str | None = None,
    caption: str | None = None,
    entities=None,
    caption_entities=None,
    reply_to_message=None,
):
    user = SimpleNamespace(id=12345, username="alice", first_name="Alice")
    message = SimpleNamespace(
        chat=SimpleNamespace(type=chat_type, is_forum=False),
        chat_id=-100123,
        text=text,
        caption=caption,
        entities=entities or [],
        caption_entities=caption_entities or [],
        reply_to_message=reply_to_message,
        photo=None,
        voice=None,
        audio=None,
        document=None,
        media_group_id=None,
        message_thread_id=None,
        message_id=1,
    )
    return SimpleNamespace(message=message, effective_user=user)


@pytest.mark.asyncio
async def test_start_creates_separate_pools_with_proxy(monkeypatch) -> None:
    _FakeHTTPXRequest.clear()
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

    assert len(_FakeHTTPXRequest.instances) == 2
    api_req, poll_req = _FakeHTTPXRequest.instances
    assert api_req.kwargs["proxy"] == config.proxy
    assert poll_req.kwargs["proxy"] == config.proxy
    assert api_req.kwargs["connection_pool_size"] == 32
    assert poll_req.kwargs["connection_pool_size"] == 4
    assert builder.request_value is api_req
    assert builder.get_updates_request_value is poll_req
    assert any(cmd.command == "status" for cmd in app.bot.commands)


@pytest.mark.asyncio
async def test_start_respects_custom_pool_config(monkeypatch) -> None:
    _FakeHTTPXRequest.clear()
    config = TelegramConfig(
        enabled=True,
        token="123:abc",
        allow_from=["*"],
        connection_pool_size=32,
        pool_timeout=10.0,
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

    api_req = _FakeHTTPXRequest.instances[0]
    poll_req = _FakeHTTPXRequest.instances[1]
    assert api_req.kwargs["connection_pool_size"] == 32
    assert api_req.kwargs["pool_timeout"] == 10.0
    assert poll_req.kwargs["pool_timeout"] == 10.0


@pytest.mark.asyncio
async def test_send_text_retries_on_timeout() -> None:
    """_send_text retries on TimedOut before succeeding."""
    from telegram.error import TimedOut

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    call_count = 0
    original_send = channel._app.bot.send_message

    async def flaky_send(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise TimedOut()
        return await original_send(**kwargs)

    channel._app.bot.send_message = flaky_send

    import nanobot.channels.telegram as tg_mod
    orig_delay = tg_mod._SEND_RETRY_BASE_DELAY
    tg_mod._SEND_RETRY_BASE_DELAY = 0.01
    try:
        await channel._send_text(123, "hello", None, {})
    finally:
        tg_mod._SEND_RETRY_BASE_DELAY = orig_delay

    assert call_count == 3
    assert len(channel._app.bot.sent_messages) == 1


@pytest.mark.asyncio
async def test_send_text_gives_up_after_max_retries() -> None:
    """_send_text raises TimedOut after exhausting all retries."""
    from telegram.error import TimedOut

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    async def always_timeout(**kwargs):
        raise TimedOut()

    channel._app.bot.send_message = always_timeout

    import nanobot.channels.telegram as tg_mod
    orig_delay = tg_mod._SEND_RETRY_BASE_DELAY
    tg_mod._SEND_RETRY_BASE_DELAY = 0.01
    try:
        with pytest.raises(TimedOut):
            await channel._send_text(123, "hello", None, {})
    finally:
        tg_mod._SEND_RETRY_BASE_DELAY = orig_delay

    assert channel._app.bot.sent_messages == []


@pytest.mark.asyncio
async def test_on_error_logs_network_issues_as_warning(monkeypatch) -> None:
    from telegram.error import NetworkError

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    recorded: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "nanobot.channels.telegram.logger.warning",
        lambda message, error: recorded.append(("warning", message.format(error))),
    )
    monkeypatch.setattr(
        "nanobot.channels.telegram.logger.error",
        lambda message, error: recorded.append(("error", message.format(error))),
    )

    await channel._on_error(object(), SimpleNamespace(error=NetworkError("proxy disconnected")))

    assert recorded == [("warning", "Telegram network issue: proxy disconnected")]


@pytest.mark.asyncio
async def test_on_error_keeps_non_network_exceptions_as_error(monkeypatch) -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    recorded: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "nanobot.channels.telegram.logger.warning",
        lambda message, error: recorded.append(("warning", message.format(error))),
    )
    monkeypatch.setattr(
        "nanobot.channels.telegram.logger.error",
        lambda message, error: recorded.append(("error", message.format(error))),
    )

    await channel._on_error(object(), SimpleNamespace(error=RuntimeError("boom")))

    assert recorded == [("error", "Telegram error: boom")]


@pytest.mark.asyncio
async def test_send_delta_stream_end_raises_and_keeps_buffer_on_failure() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._app.bot.edit_message_text = AsyncMock(side_effect=RuntimeError("boom"))
    channel._stream_bufs["123"] = _StreamBuf(text="hello", message_id=7, last_edit=0.0)

    with pytest.raises(RuntimeError, match="boom"):
        await channel.send_delta("123", "", {"_stream_end": True})

    assert "123" in channel._stream_bufs


@pytest.mark.asyncio
async def test_send_delta_stream_end_treats_not_modified_as_success() -> None:
    from telegram.error import BadRequest

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._app.bot.edit_message_text = AsyncMock(side_effect=BadRequest("Message is not modified"))
    channel._stream_bufs["123"] = _StreamBuf(text="hello", message_id=7, last_edit=0.0, stream_id="s:0")

    await channel.send_delta("123", "", {"_stream_end": True, "_stream_id": "s:0"})

    assert "123" not in channel._stream_bufs


@pytest.mark.asyncio
async def test_send_delta_new_stream_id_replaces_stale_buffer() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._stream_bufs["123"] = _StreamBuf(
        text="hello",
        message_id=7,
        last_edit=0.0,
        stream_id="old:0",
    )

    await channel.send_delta("123", "world", {"_stream_delta": True, "_stream_id": "new:0"})

    buf = channel._stream_bufs["123"]
    assert buf.text == "world"
    assert buf.stream_id == "new:0"
    assert buf.message_id == 1


@pytest.mark.asyncio
async def test_send_delta_incremental_edit_treats_not_modified_as_success() -> None:
    from telegram.error import BadRequest

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._stream_bufs["123"] = _StreamBuf(text="hello", message_id=7, last_edit=0.0, stream_id="s:0")
    channel._app.bot.edit_message_text = AsyncMock(side_effect=BadRequest("Message is not modified"))

    await channel.send_delta("123", "", {"_stream_delta": True, "_stream_id": "s:0"})

    assert channel._stream_bufs["123"].last_edit > 0.0


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


def test_telegram_group_policy_defaults_to_mention() -> None:
    assert TelegramConfig().group_policy == "mention"


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
async def test_send_remote_media_url_after_security_validation(monkeypatch) -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    monkeypatch.setattr("nanobot.channels.telegram.validate_url_target", lambda url: (True, ""))

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="",
            media=["https://example.com/cat.jpg"],
        )
    )

    assert channel._app.bot.sent_media == [
        {
            "kind": "photo",
            "chat_id": 123,
            "photo": "https://example.com/cat.jpg",
            "reply_parameters": None,
        }
    ]


@pytest.mark.asyncio
async def test_send_blocks_unsafe_remote_media_url(monkeypatch) -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    monkeypatch.setattr(
        "nanobot.channels.telegram.validate_url_target",
        lambda url: (False, "Blocked: example.com resolves to private/internal address 127.0.0.1"),
    )

    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="",
            media=["http://example.com/internal.jpg"],
        )
    )

    assert channel._app.bot.sent_media == []
    assert channel._app.bot.sent_messages == [
        {
            "chat_id": 123,
            "text": "[Failed to send: internal.jpg]",
            "reply_parameters": None,
        }
    ]


@pytest.mark.asyncio
async def test_group_policy_mention_ignores_unmentioned_group_message() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    await channel._on_message(_make_telegram_update(text="hello everyone"), None)

    assert handled == []
    assert channel._app.bot.get_me_calls == 1


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_text_mention_and_caches_bot_identity() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    mention = SimpleNamespace(type="mention", offset=0, length=13)
    await channel._on_message(_make_telegram_update(text="@nanobot_test hi", entities=[mention]), None)
    await channel._on_message(_make_telegram_update(text="@nanobot_test again", entities=[mention]), None)

    assert len(handled) == 2
    assert channel._app.bot.get_me_calls == 1


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_caption_mention() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    mention = SimpleNamespace(type="mention", offset=0, length=13)
    await channel._on_message(
        _make_telegram_update(caption="@nanobot_test photo", caption_entities=[mention]),
        None,
    )

    assert len(handled) == 1
    assert handled[0]["content"] == "@nanobot_test photo"


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_reply_to_bot() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    reply = SimpleNamespace(from_user=SimpleNamespace(id=999))
    await channel._on_message(_make_telegram_update(text="reply", reply_to_message=reply), None)

    assert len(handled) == 1


@pytest.mark.asyncio
async def test_group_policy_open_accepts_plain_group_message() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    await channel._on_message(_make_telegram_update(text="hello group"), None)

    assert len(handled) == 1
    assert channel._app.bot.get_me_calls == 0


def test_extract_reply_context_no_reply() -> None:
    """When there is no reply_to_message, _extract_reply_context returns None."""
    message = SimpleNamespace(reply_to_message=None)
    assert TelegramChannel._extract_reply_context(message) is None


def test_extract_reply_context_with_text() -> None:
    """When reply has text, return prefixed string."""
    reply = SimpleNamespace(text="Hello world", caption=None)
    message = SimpleNamespace(reply_to_message=reply)
    assert TelegramChannel._extract_reply_context(message) == "[Reply to: Hello world]"


def test_extract_reply_context_with_caption_only() -> None:
    """When reply has only caption (no text), caption is used."""
    reply = SimpleNamespace(text=None, caption="Photo caption")
    message = SimpleNamespace(reply_to_message=reply)
    assert TelegramChannel._extract_reply_context(message) == "[Reply to: Photo caption]"


def test_extract_reply_context_truncation() -> None:
    """Reply text is truncated at TELEGRAM_REPLY_CONTEXT_MAX_LEN."""
    long_text = "x" * (TELEGRAM_REPLY_CONTEXT_MAX_LEN + 100)
    reply = SimpleNamespace(text=long_text, caption=None)
    message = SimpleNamespace(reply_to_message=reply)
    result = TelegramChannel._extract_reply_context(message)
    assert result is not None
    assert result.startswith("[Reply to: ")
    assert result.endswith("...]")
    assert len(result) == len("[Reply to: ]") + TELEGRAM_REPLY_CONTEXT_MAX_LEN + len("...")


def test_extract_reply_context_no_text_returns_none() -> None:
    """When reply has no text/caption, _extract_reply_context returns None (media handled separately)."""
    reply = SimpleNamespace(text=None, caption=None)
    message = SimpleNamespace(reply_to_message=reply)
    assert TelegramChannel._extract_reply_context(message) is None


@pytest.mark.asyncio
async def test_on_message_includes_reply_context() -> None:
    """When user replies to a message, content passed to bus starts with reply context."""
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    handled = []
    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)
    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    reply = SimpleNamespace(text="Hello", message_id=2, from_user=SimpleNamespace(id=1))
    update = _make_telegram_update(text="translate this", reply_to_message=reply)
    await channel._on_message(update, None)

    assert len(handled) == 1
    assert handled[0]["content"].startswith("[Reply to: Hello]")
    assert "translate this" in handled[0]["content"]


@pytest.mark.asyncio
async def test_download_message_media_returns_path_when_download_succeeds(
    monkeypatch, tmp_path
) -> None:
    """_download_message_media returns (paths, content_parts) when bot.get_file and download succeed."""
    media_dir = tmp_path / "media" / "telegram"
    media_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "nanobot.channels.telegram.get_media_dir",
        lambda channel=None: media_dir if channel else tmp_path / "media",
    )

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._app.bot.get_file = AsyncMock(
        return_value=SimpleNamespace(download_to_drive=AsyncMock(return_value=None))
    )

    msg = SimpleNamespace(
        photo=[SimpleNamespace(file_id="fid123", mime_type="image/jpeg")],
        voice=None,
        audio=None,
        document=None,
        video=None,
        video_note=None,
        animation=None,
    )
    paths, parts = await channel._download_message_media(msg)
    assert len(paths) == 1
    assert len(parts) == 1
    assert "fid123" in paths[0]
    assert "[image:" in parts[0]


@pytest.mark.asyncio
async def test_download_message_media_uses_file_unique_id_when_available(
    monkeypatch, tmp_path
) -> None:
    media_dir = tmp_path / "media" / "telegram"
    media_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "nanobot.channels.telegram.get_media_dir",
        lambda channel=None: media_dir if channel else tmp_path / "media",
    )

    downloaded: dict[str, str] = {}

    async def _download_to_drive(path: str) -> None:
        downloaded["path"] = path

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    app = _FakeApp(lambda: None)
    app.bot.get_file = AsyncMock(
        return_value=SimpleNamespace(download_to_drive=_download_to_drive)
    )
    channel._app = app

    msg = SimpleNamespace(
        photo=[
            SimpleNamespace(
                file_id="file-id-that-should-not-be-used",
                file_unique_id="stable-unique-id",
                mime_type="image/jpeg",
                file_name=None,
            )
        ],
        voice=None,
        audio=None,
        document=None,
        video=None,
        video_note=None,
        animation=None,
    )

    paths, parts = await channel._download_message_media(msg)

    assert downloaded["path"].endswith("stable-unique-id.jpg")
    assert paths == [str(media_dir / "stable-unique-id.jpg")]
    assert parts == [f"[image: {media_dir / 'stable-unique-id.jpg'}]"]


@pytest.mark.asyncio
async def test_on_message_attaches_reply_to_media_when_available(monkeypatch, tmp_path) -> None:
    """When user replies to a message with media, that media is downloaded and attached to the turn."""
    media_dir = tmp_path / "media" / "telegram"
    media_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "nanobot.channels.telegram.get_media_dir",
        lambda channel=None: media_dir if channel else tmp_path / "media",
    )

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    app = _FakeApp(lambda: None)
    app.bot.get_file = AsyncMock(
        return_value=SimpleNamespace(download_to_drive=AsyncMock(return_value=None))
    )
    channel._app = app
    handled = []
    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)
    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    reply_with_photo = SimpleNamespace(
        text=None,
        caption=None,
        photo=[SimpleNamespace(file_id="reply_photo_fid", mime_type="image/jpeg")],
        document=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        animation=None,
    )
    update = _make_telegram_update(
        text="what is the image?",
        reply_to_message=reply_with_photo,
    )
    await channel._on_message(update, None)

    assert len(handled) == 1
    assert handled[0]["content"].startswith("[Reply to: [image:")
    assert "what is the image?" in handled[0]["content"]
    assert len(handled[0]["media"]) == 1
    assert "reply_photo_fid" in handled[0]["media"][0]


@pytest.mark.asyncio
async def test_on_message_reply_to_media_fallback_when_download_fails() -> None:
    """When reply has media but download fails, no media attached and no reply tag."""
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._app.bot.get_file = None
    handled = []
    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)
    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    reply_with_photo = SimpleNamespace(
        text=None,
        caption=None,
        photo=[SimpleNamespace(file_id="x", mime_type="image/jpeg")],
        document=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        animation=None,
    )
    update = _make_telegram_update(text="what is this?", reply_to_message=reply_with_photo)
    await channel._on_message(update, None)

    assert len(handled) == 1
    assert "what is this?" in handled[0]["content"]
    assert handled[0]["media"] == []


@pytest.mark.asyncio
async def test_on_message_reply_to_caption_and_media(monkeypatch, tmp_path) -> None:
    """When replying to a message with caption + photo, both text context and media are included."""
    media_dir = tmp_path / "media" / "telegram"
    media_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "nanobot.channels.telegram.get_media_dir",
        lambda channel=None: media_dir if channel else tmp_path / "media",
    )

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    app = _FakeApp(lambda: None)
    app.bot.get_file = AsyncMock(
        return_value=SimpleNamespace(download_to_drive=AsyncMock(return_value=None))
    )
    channel._app = app
    handled = []
    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)
    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    reply_with_caption_and_photo = SimpleNamespace(
        text=None,
        caption="A cute cat",
        photo=[SimpleNamespace(file_id="cat_fid", mime_type="image/jpeg")],
        document=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        animation=None,
    )
    update = _make_telegram_update(
        text="what breed is this?",
        reply_to_message=reply_with_caption_and_photo,
    )
    await channel._on_message(update, None)

    assert len(handled) == 1
    assert "[Reply to: A cute cat]" in handled[0]["content"]
    assert "what breed is this?" in handled[0]["content"]
    assert len(handled[0]["media"]) == 1
    assert "cat_fid" in handled[0]["media"][0]


@pytest.mark.asyncio
async def test_forward_command_does_not_inject_reply_context() -> None:
    """Slash commands forwarded via _forward_command must not include reply context."""
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    handled = []
    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)
    channel._handle_message = capture_handle

    reply = SimpleNamespace(text="some old message", message_id=2, from_user=SimpleNamespace(id=1))
    update = _make_telegram_update(text="/new", reply_to_message=reply)
    await channel._forward_command(update, None)

    assert len(handled) == 1
    assert handled[0]["content"] == "/new"


@pytest.mark.asyncio
async def test_on_help_includes_restart_command() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    update = _make_telegram_update(text="/help", chat_type="private")
    update.message.reply_text = AsyncMock()

    await channel._on_help(update, None)

    update.message.reply_text.assert_awaited_once()
    help_text = update.message.reply_text.await_args.args[0]
    assert "/coding" in help_text
    assert "/coding help" in help_text
    assert "/restart" in help_text
    assert "/status" in help_text


def test_bot_commands_include_coding_entry() -> None:
    commands = {command.command: command.description for command in TelegramChannel.BOT_COMMANDS}

    assert commands["coding"] == "Start or manage coding tasks"
