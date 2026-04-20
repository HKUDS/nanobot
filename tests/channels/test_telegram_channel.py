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
        self.start_polling_kwargs = None

    async def start_polling(self, **kwargs) -> None:
        self.start_polling_kwargs = kwargs
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
    location=None,
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
        location=location,
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
    assert callable(app.updater.start_polling_kwargs["error_callback"])
    assert any(cmd.command == "status" for cmd in app.bot.commands)
    assert any(cmd.command == "dream" for cmd in app.bot.commands)
    assert any(cmd.command == "dream_log" for cmd in app.bot.commands)
    assert any(cmd.command == "dream_restore" for cmd in app.bot.commands)


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
async def test_on_error_summarizes_empty_network_error(monkeypatch) -> None:
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

    await channel._on_error(object(), SimpleNamespace(error=NetworkError("")))

    assert recorded == [("warning", "Telegram network issue: NetworkError")]


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
async def test_send_delta_stream_end_does_not_fallback_on_network_timeout() -> None:
    """TimedOut during HTML edit should propagate, never fall back to plain text."""
    from telegram.error import TimedOut

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    # _call_with_retry retries TimedOut up to 3 times, so the mock will be called
    # multiple times – but all calls must be with parse_mode="HTML" (no plain fallback).
    channel._app.bot.edit_message_text = AsyncMock(side_effect=TimedOut("network timeout"))
    channel._stream_bufs["123"] = _StreamBuf(text="hello", message_id=7, last_edit=0.0)

    with pytest.raises(TimedOut, match="network timeout"):
        await channel.send_delta("123", "", {"_stream_end": True})

    # Every call to edit_message_text must have used parse_mode="HTML" —
    # no plain-text fallback call should have been made.
    for call in channel._app.bot.edit_message_text.call_args_list:
        assert call.kwargs.get("parse_mode") == "HTML"
    # Buffer should still be present (not cleaned up on error)
    assert "123" in channel._stream_bufs


@pytest.mark.asyncio
async def test_send_delta_stream_end_does_not_fallback_on_network_error() -> None:
    """NetworkError during HTML edit should propagate, never fall back to plain text."""
    from telegram.error import NetworkError

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._app.bot.edit_message_text = AsyncMock(side_effect=NetworkError("connection reset"))
    channel._stream_bufs["123"] = _StreamBuf(text="hello", message_id=7, last_edit=0.0)

    with pytest.raises(NetworkError, match="connection reset"):
        await channel.send_delta("123", "", {"_stream_end": True})

    # Every call to edit_message_text must have used parse_mode="HTML" —
    # no plain-text fallback call should have been made.
    for call in channel._app.bot.edit_message_text.call_args_list:
        assert call.kwargs.get("parse_mode") == "HTML"
    # Buffer should still be present (not cleaned up on error)
    assert "123" in channel._stream_bufs


@pytest.mark.asyncio
async def test_send_delta_stream_end_falls_back_on_bad_request() -> None:
    """BadRequest (HTML parse error) should still trigger plain-text fallback."""
    from telegram.error import BadRequest

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    # First call (HTML) raises BadRequest, second call (plain) succeeds
    channel._app.bot.edit_message_text = AsyncMock(
        side_effect=[BadRequest("Can't parse entities"), None]
    )
    channel._stream_bufs["123"] = _StreamBuf(text="hello <bad>", message_id=7, last_edit=0.0)

    await channel.send_delta("123", "", {"_stream_end": True})

    # edit_message_text should have been called twice: once for HTML, once for plain fallback
    assert channel._app.bot.edit_message_text.call_count == 2
    # Second call should not use parse_mode="HTML"
    second_call_kwargs = channel._app.bot.edit_message_text.call_args_list[1].kwargs
    assert "parse_mode" not in second_call_kwargs or second_call_kwargs.get("parse_mode") is None
    # Buffer should be cleaned up on success
    assert "123" not in channel._stream_bufs


@pytest.mark.asyncio
async def test_send_delta_stream_end_splits_oversized_reply() -> None:
    """Final streamed reply exceeding Telegram limit is split into chunks.

    The fix converts markdown to HTML first, then splits by 4096 (actual Telegram
    limit), ensuring the edited message always fits within Telegram's constraint.
    Previously, the code split by 4000 (TELEGRAM_MAX_MESSAGE_LEN) before HTML
    conversion, which could still overflow when HTML tags were added.
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._app.bot.edit_message_text = AsyncMock()
    channel._app.bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=99))

    oversized = "x" * (4000 + 500)
    channel._stream_bufs["123"] = _StreamBuf(text=oversized, message_id=7, last_edit=0.0)

    await channel.send_delta("123", "", {"_stream_end": True})

    channel._app.bot.edit_message_text.assert_called_once()
    edit_text = channel._app.bot.edit_message_text.call_args.kwargs.get("text", "")
    assert len(edit_text) <= 4096, f"edit_text length {len(edit_text)} exceeds Telegram's 4096 limit"

    channel._app.bot.send_message.assert_called_once()
    send_text = channel._app.bot.send_message.call_args.kwargs.get("text", "")
    assert len(send_text) <= 4096
    assert "123" not in channel._stream_bufs


@pytest.mark.asyncio
async def test_send_delta_stream_end_html_expansion_does_not_overflow() -> None:
    """Markdown that expands when converted to HTML is still split correctly.

    This is the actual bug from issue #3315: markdown like **bold** expands to
    <b>bold</b>, adding ~33% characters. A 3600-char message with heavy markdown
    could become 4800+ chars after HTML conversion, exceeding 4096 limit.
    The fix converts to HTML first, THEN splits by 4096.
    """
    from nanobot.channels.telegram import _markdown_to_telegram_html

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._app.bot.edit_message_text = AsyncMock()
    channel._app.bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=99))

    markdown_text = "**bold** " * 400  # 3600 chars raw, expands ~33% to 4800 HTML
    raw_len = len(markdown_text)
    html_len = len(_markdown_to_telegram_html(markdown_text))
    assert html_len > 4096, f"Test precondition failed: HTML should exceed 4096 (was {html_len})"

    channel._stream_bufs["123"] = _StreamBuf(text=markdown_text, message_id=7, last_edit=0.0)

    await channel.send_delta("123", "", {"_stream_end": True})

    channel._app.bot.edit_message_text.assert_called_once()
    edit_text = channel._app.bot.edit_message_text.call_args.kwargs.get("text", "")
    assert len(edit_text) <= 4096, (
        f"HTML text length {len(edit_text)} exceeds Telegram's 4096 limit. "
        f"Raw was {raw_len}, HTML was {html_len}."
    )

    channel._app.bot.send_message.assert_called_once()
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


@pytest.mark.asyncio
async def test_send_delta_incremental_edit_splits_oversized_buffer() -> None:
    """Mid-stream overflow: once buf.text exceeds Telegram's limit, split into
    chunks, edit the current message with the first chunk, and re-anchor the
    buffer to a new message for the tail so further deltas keep streaming."""
    from nanobot.channels.telegram import TELEGRAM_MAX_MESSAGE_LEN

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    channel._app.bot.edit_message_text = AsyncMock()
    channel._app.bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=99))

    oversized = "x" * (TELEGRAM_MAX_MESSAGE_LEN + 500)
    channel._stream_bufs["123"] = _StreamBuf(
        text=oversized, message_id=7, last_edit=0.0, stream_id="s:0"
    )

    await channel.send_delta("123", "y", {"_stream_delta": True, "_stream_id": "s:0"})

    channel._app.bot.edit_message_text.assert_called_once()
    edit_text = channel._app.bot.edit_message_text.call_args.kwargs.get("text", "")
    assert len(edit_text) <= TELEGRAM_MAX_MESSAGE_LEN

    channel._app.bot.send_message.assert_called_once()
    buf = channel._stream_bufs["123"]
    assert buf.message_id == 99
    assert len(buf.text) <= TELEGRAM_MAX_MESSAGE_LEN
    assert buf.last_edit > 0.0


@pytest.mark.asyncio
async def test_send_delta_initial_send_keeps_message_in_thread() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    await channel.send_delta(
        "123",
        "hello",
        {"_stream_delta": True, "_stream_id": "s:0", "message_thread_id": 42},
    )

    assert channel._app.bot.sent_messages[0]["message_thread_id"] == 42


def test_derive_topic_session_key_uses_thread_id() -> None:
    message = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup"),
        chat_id=-100123,
        message_thread_id=42,
    )

    assert TelegramChannel._derive_topic_session_key(message) == "telegram:-100123:topic:42"


def test_derive_topic_session_key_private_dm_thread() -> None:
    """Private DM threads (Telegram Threaded Mode) must get their own session key."""
    message = SimpleNamespace(
        chat=SimpleNamespace(type="private"),
        chat_id=999,
        message_thread_id=7,
    )
    assert TelegramChannel._derive_topic_session_key(message) == "telegram:999:topic:7"


def test_derive_topic_session_key_none_without_thread() -> None:
    """No thread id → no topic session key, regardless of chat type."""
    for chat_type in ("private", "supergroup", "group"):
        message = SimpleNamespace(
            chat=SimpleNamespace(type=chat_type),
            chat_id=123,
            message_thread_id=None,
        )
        assert TelegramChannel._derive_topic_session_key(message) is None


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


@pytest.mark.asyncio
async def test_extract_reply_context_no_reply() -> None:
    """When there is no reply_to_message, _extract_reply_context returns None."""
    channel = TelegramChannel(TelegramConfig(enabled=True, token="123:abc"), MessageBus())
    message = SimpleNamespace(reply_to_message=None)
    assert await channel._extract_reply_context(message) is None


@pytest.mark.asyncio
async def test_extract_reply_context_with_text() -> None:
    """When reply has text, return prefixed string."""
    channel = TelegramChannel(TelegramConfig(enabled=True, token="123:abc"), MessageBus())
    channel._app = _FakeApp(lambda: None)
    reply = SimpleNamespace(text="Hello world", caption=None, from_user=SimpleNamespace(id=2, username="testuser", first_name="Test"))
    message = SimpleNamespace(reply_to_message=reply)
    assert await channel._extract_reply_context(message) == "[Reply to @testuser: Hello world]"


@pytest.mark.asyncio
async def test_extract_reply_context_with_caption_only() -> None:
    """When reply has only caption (no text), caption is used."""
    channel = TelegramChannel(TelegramConfig(enabled=True, token="123:abc"), MessageBus())
    channel._app = _FakeApp(lambda: None)
    reply = SimpleNamespace(text=None, caption="Photo caption", from_user=SimpleNamespace(id=2, username=None, first_name="Test"))
    message = SimpleNamespace(reply_to_message=reply)
    assert await channel._extract_reply_context(message) == "[Reply to Test: Photo caption]"


@pytest.mark.asyncio
async def test_extract_reply_context_truncation() -> None:
    """Reply text is truncated at TELEGRAM_REPLY_CONTEXT_MAX_LEN."""
    channel = TelegramChannel(TelegramConfig(enabled=True, token="123:abc"), MessageBus())
    channel._app = _FakeApp(lambda: None)
    long_text = "x" * (TELEGRAM_REPLY_CONTEXT_MAX_LEN + 100)
    reply = SimpleNamespace(text=long_text, caption=None, from_user=SimpleNamespace(id=2, username=None, first_name=None))
    message = SimpleNamespace(reply_to_message=reply)
    result = await channel._extract_reply_context(message)
    assert result is not None
    assert result.startswith("[Reply to: ")
    assert result.endswith("...]")
    assert len(result) == len("[Reply to: ]") + TELEGRAM_REPLY_CONTEXT_MAX_LEN + len("...")


@pytest.mark.asyncio
async def test_extract_reply_context_no_text_returns_none() -> None:
    """When reply has no text/caption, _extract_reply_context returns None (media handled separately)."""
    channel = TelegramChannel(TelegramConfig(enabled=True, token="123:abc"), MessageBus())
    reply = SimpleNamespace(text=None, caption=None)
    message = SimpleNamespace(reply_to_message=reply)
    assert await channel._extract_reply_context(message) is None


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
async def test_forward_command_preserves_dream_log_args_and_strips_bot_suffix() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    update = _make_telegram_update(text="/dream-log@nanobot_test deadbeef", reply_to_message=None)

    await channel._forward_command(update, None)

    assert len(handled) == 1
    assert handled[0]["content"] == "/dream-log deadbeef"


@pytest.mark.asyncio
async def test_forward_command_normalizes_telegram_safe_dream_aliases() -> None:
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    update = _make_telegram_update(text="/dream_restore@nanobot_test deadbeef", reply_to_message=None)

    await channel._forward_command(update, None)

    assert len(handled) == 1
    assert handled[0]["content"] == "/dream-restore deadbeef"


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
    assert "/restart" in help_text
    assert "/status" in help_text
    assert "/dream" in help_text
    assert "/dream-log" in help_text
    assert "/dream-restore" in help_text


@pytest.mark.asyncio
async def test_on_message_location_content() -> None:
    """Location messages are forwarded as [location: lat, lon] content."""
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

    location = SimpleNamespace(latitude=48.8566, longitude=2.3522)
    update = _make_telegram_update(location=location)
    await channel._on_message(update, None)

    assert len(handled) == 1
    assert handled[0]["content"] == "[location: 48.8566, 2.3522]"


@pytest.mark.asyncio
async def test_on_message_location_with_text() -> None:
    """Location messages with accompanying text include both in content."""
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

    location = SimpleNamespace(latitude=51.5074, longitude=-0.1278)
    update = _make_telegram_update(text="meet me here", location=location)
    await channel._on_message(update, None)

    assert len(handled) == 1
    assert "meet me here" in handled[0]["content"]
    assert "[location: 51.5074, -0.1278]" in handled[0]["content"]


# ---------------------------------------------------------------------------
# Tests for retry amplification fix (issue #3050)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_text_does_not_fallback_on_network_timeout() -> None:
    """TimedOut should propagate immediately, NOT trigger plain-text fallback.

    Before the fix, _send_text caught ALL exceptions (including TimedOut)
    and retried as plain text, doubling connection demand during pool
    exhaustion — see issue #3050.
    """
    from telegram.error import TimedOut

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    call_count = 0

    async def always_timeout(**kwargs):
        nonlocal call_count
        call_count += 1
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

    # With the fix: only _call_with_retry's 3 HTML attempts (no plain fallback).
    # Before the fix: 3 HTML + 3 plain = 6 attempts.
    assert call_count == 3, (
        f"Expected 3 calls (HTML retries only), got {call_count} "
        "(plain-text fallback should not trigger on TimedOut)"
    )


@pytest.mark.asyncio
async def test_send_text_does_not_fallback_on_network_error() -> None:
    """NetworkError should propagate immediately, NOT trigger plain-text fallback."""
    from telegram.error import NetworkError

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    call_count = 0

    async def always_network_error(**kwargs):
        nonlocal call_count
        call_count += 1
        raise NetworkError("Connection reset")

    channel._app.bot.send_message = always_network_error

    import nanobot.channels.telegram as tg_mod
    orig_delay = tg_mod._SEND_RETRY_BASE_DELAY
    tg_mod._SEND_RETRY_BASE_DELAY = 0.01
    try:
        with pytest.raises(NetworkError):
            await channel._send_text(123, "hello", None, {})
    finally:
        tg_mod._SEND_RETRY_BASE_DELAY = orig_delay

    # _call_with_retry does NOT retry NetworkError (only TimedOut/RetryAfter),
    # so it raises after 1 attempt. The fix prevents plain-text fallback.
    # Before the fix: 1 HTML + 1 plain = 2. After the fix: 1 HTML only.
    assert call_count == 1, (
        f"Expected 1 call (HTML only, no plain fallback), got {call_count}"
    )


@pytest.mark.asyncio
async def test_send_text_falls_back_on_bad_request() -> None:
    """BadRequest (HTML parse error) should still trigger plain-text fallback."""
    from telegram.error import BadRequest

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    original_send = channel._app.bot.send_message
    html_call_count = 0

    async def html_fails(**kwargs):
        nonlocal html_call_count
        if kwargs.get("parse_mode") == "HTML":
            html_call_count += 1
            raise BadRequest("Can't parse entities")
        return await original_send(**kwargs)

    channel._app.bot.send_message = html_fails

    import nanobot.channels.telegram as tg_mod
    orig_delay = tg_mod._SEND_RETRY_BASE_DELAY
    tg_mod._SEND_RETRY_BASE_DELAY = 0.01
    try:
        await channel._send_text(123, "hello **world**", None, {})
    finally:
        tg_mod._SEND_RETRY_BASE_DELAY = orig_delay

    # HTML attempt failed with BadRequest → fallback to plain text succeeds.
    assert html_call_count == 1, f"Expected 1 HTML attempt, got {html_call_count}"
    assert len(channel._app.bot.sent_messages) == 1
    # Plain text send should NOT have parse_mode
    assert channel._app.bot.sent_messages[0].get("parse_mode") is None


@pytest.mark.asyncio
async def test_send_text_bad_request_plain_fallback_exhausted() -> None:
    """When both HTML and plain-text fallback fail with BadRequest, the error propagates."""
    from telegram.error import BadRequest

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    call_count = 0

    async def always_bad_request(**kwargs):
        nonlocal call_count
        call_count += 1
        raise BadRequest("Bad request")

    channel._app.bot.send_message = always_bad_request

    import nanobot.channels.telegram as tg_mod
    orig_delay = tg_mod._SEND_RETRY_BASE_DELAY
    tg_mod._SEND_RETRY_BASE_DELAY = 0.01
    try:
        with pytest.raises(BadRequest):
            await channel._send_text(123, "hello", None, {})
    finally:
        tg_mod._SEND_RETRY_BASE_DELAY = orig_delay

    # _call_with_retry does NOT retry BadRequest (only TimedOut/RetryAfter),
    # so HTML fails after 1 attempt → fallback to plain also fails after 1 attempt.
    # Before the fix: 2 total. After the fix: still 2 (BadRequest SHOULD fallback).
    assert call_count == 2, f"Expected 2 calls (1 HTML + 1 plain), got {call_count}"
