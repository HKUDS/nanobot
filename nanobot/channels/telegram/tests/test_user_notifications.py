from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram.runtime import TelegramChannel, TelegramConfig
from nanobot.channels.telegram.user_notifications import notification_receipt_id


def test_only_explicit_automation_is_notification():
    assert notification_receipt_id({}, "ordinary answer") is None
    assert notification_receipt_id({"message_id": 11}, "ordinary answer") is None
    assert notification_receipt_id({"_local_trigger": "not-a-trigger"}, "x") is None
    assert notification_receipt_id({"_cron_trigger": {"run_id": ""}}, "x") is None
    assert notification_receipt_id({"_local_trigger": {"delivery_id": "x"}}, " ") is None


def test_idempotent_private_bounded_receipt_identity():
    meta = {"_local_trigger": {"delivery_id": "private-id", "secret": "secret"}}
    first = notification_receipt_id(meta, "calendar changed")
    assert first == notification_receipt_id(meta, "calendar changed")
    assert first != notification_receipt_id(meta, "another batch")
    assert first != notification_receipt_id({"_cron_trigger": {"run_id": "private-id"}}, "calendar changed")
    assert first and len(first) == 69 and "private-id" not in first and "secret" not in first


# Real channel send paths with a fake network edge: no Telegram traffic.
@pytest.fixture
def channel():
    channel = TelegramChannel(TelegramConfig(
        token="123:fixture", allow_from=["7"], rich_messages=False,
        technical={"sharedInbox": True, "mainChatId": "7"},
    ), MessageBus())
    channel._app = SimpleNamespace(bot=SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=44)),
        edit_message_text=AsyncMock(),
        do_api_request=AsyncMock(return_value=True),
    ))
    channel._app_ready.set()
    channel.on_notification_delivered = AsyncMock()
    return channel


async def test_receipt_only_after_confirmed_send_and_only_for_owner(channel):
    metadata = {"_local_trigger": {"delivery_id": "trigger-1"}}
    msg = OutboundMessage(channel="telegram", chat_id="7", content="Calendar changed", metadata=metadata)
    await channel.send(msg)
    callback = channel.on_notification_delivered
    callback.assert_awaited_once_with(msg.content, notification_receipt_id(metadata, msg.content))
    callback.reset_mock()
    await channel.send(OutboundMessage(channel="telegram", chat_id="8", content="Other", metadata=metadata))
    await channel.send(OutboundMessage(channel="telegram", chat_id="7", content="Ordinary"))
    await channel.send(OutboundMessage(channel="telegram", chat_id="7", content="Tool progress", metadata=metadata, event=ProgressEvent()))
    callback.assert_not_awaited()


async def test_failed_send_creates_no_receipt_and_failed_receipt_never_retries_send(channel):
    msg = OutboundMessage(channel="telegram", chat_id="7", content="Calendar changed", metadata={"_user_notification": {"id": "1"}})
    channel._app.bot.send_message.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError):
        await channel.send(msg)
    channel.on_notification_delivered.assert_not_awaited()
    channel._app.bot.send_message.side_effect = None
    channel._app.bot.send_message.reset_mock()
    channel.on_notification_delivered.side_effect = OSError("disk")
    await channel.send(msg)
    channel._app.bot.send_message.assert_awaited_once()


async def test_streamed_automation_receipt_waits_for_final_edit(channel):
    metadata = {"_cron_trigger": {"run_id": "run-1"}}
    await channel.send_delta("7", "Calendar changed", metadata, stream_id="s")
    channel.on_notification_delivered.assert_not_awaited()
    await channel.send_delta("7", "", metadata, stream_id="s", stream_end=True)
    channel.on_notification_delivered.assert_awaited_once_with("Calendar changed", notification_receipt_id(metadata, "Calendar changed"))
    await channel.send_delta("7", "", metadata, stream_id="s", stream_end=True)
    assert channel.on_notification_delivered.await_count == 1


async def _overflow_notification(channel, *, rounds=1):
    metadata = {"_cron_trigger": {"run_id": "long-stream"}}
    parts = ["CONFIRMED-PREFIX-" + "A" * 2800]
    await channel.send_delta("7", parts[0], metadata, stream_id="long")
    for index in range(rounds):
        parts.append(chr(ord("B") + index) * 2800 + f"-CONFIRMED-{index}-END")
        channel._stream_bufs["7"].last_edit = 0  # Deterministic; no sleep.
        await channel.send_delta("7", parts[-1], metadata, stream_id="long")
    assert channel._app.bot.send_message.await_count >= 2
    channel.on_notification_delivered.assert_not_awaited()
    return metadata, "".join(parts)


@pytest.mark.parametrize("rounds", [1, 5])
@pytest.mark.parametrize("final_mode", ["html", "not-modified", "plain", "rich-enabled-late"])
async def test_long_stream_receipt_has_all_original_deltas_once(channel, rounds, final_mode):
    from telegram.error import BadRequest

    metadata, full_text = await _overflow_notification(channel, rounds=rounds)
    tail = channel._stream_bufs["7"].text
    assert len(tail) < len(full_text)  # Real overflow, not just final splitting.
    if final_mode == "not-modified":
        channel._app.bot.edit_message_text.side_effect = BadRequest("Message is not modified")
    elif final_mode == "plain":
        channel._app.bot.edit_message_text.side_effect = [BadRequest("Can't parse entities"), None]
    elif final_mode == "rich-enabled-late":
        channel.config.rich_messages = True
    await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    callback = channel.on_notification_delivered
    callback.assert_awaited_once_with(full_text, notification_receipt_id(metadata, full_text))
    assert "7" not in channel._stream_bufs
    # A legacy preview stays editable even if rich messages are enabled later.
    assert channel._app.bot.edit_message_text.await_args.kwargs["text"] == tail
    channel._app.bot.do_api_request.assert_not_awaited()
    counts = (channel._app.bot.send_message.await_count, channel._app.bot.edit_message_text.await_count)
    for _ in range(2):
        await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    assert callback.await_count == 1
    assert counts == (channel._app.bot.send_message.await_count, channel._app.bot.edit_message_text.await_count)


async def test_long_stream_receipt_failure_does_not_retry_delivery_or_end(channel):
    metadata, full_text = await _overflow_notification(channel, rounds=5)
    channel.on_notification_delivered.side_effect = OSError("fixture receipt storage unavailable")
    await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    channel.on_notification_delivered.assert_awaited_once_with(full_text, notification_receipt_id(metadata, full_text))
    counts = (channel._app.bot.send_message.await_count, channel._app.bot.edit_message_text.await_count)
    await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    assert "7" not in channel._stream_bufs
    assert channel.on_notification_delivered.await_count == 1
    assert counts == (channel._app.bot.send_message.await_count, channel._app.bot.edit_message_text.await_count)


async def test_long_stream_failed_final_edit_is_not_receipted_or_resent(channel):
    from telegram.error import NetworkError

    metadata, _ = await _overflow_notification(channel)
    send_count = channel._app.bot.send_message.await_count
    channel._app.bot.edit_message_text.reset_mock()
    channel._app.bot.edit_message_text.side_effect = NetworkError("fixture disconnected")
    with pytest.raises(NetworkError):
        await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    channel.on_notification_delivered.assert_not_awaited()
    channel._app.bot.edit_message_text.assert_awaited_once()
    assert channel._app.bot.send_message.await_count == send_count


@pytest.mark.parametrize("failure_at", [1, 2])
async def test_failed_final_extra_chunk_has_no_receipt_or_fallback_send(channel, failure_at):
    from telegram.error import NetworkError

    metadata = {"_cron_trigger": {"run_id": "final-split"}}
    await channel.send_delta("7", "A" * 2800, metadata, stream_id="long")
    channel._stream_bufs["7"].last_edit = float("inf")
    await channel.send_delta("7", "B" * 8000, metadata, stream_id="long")
    bot = channel._app.bot
    bot.send_message.reset_mock()
    bot.send_message.side_effect = [SimpleNamespace(message_id=45)] * (failure_at - 1) + [NetworkError("fixture disconnected")]
    with pytest.raises(NetworkError):
        await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    channel.on_notification_delivered.assert_not_awaited()
    assert bot.send_message.await_count == failure_at
    assert all(call.kwargs.get("parse_mode") == "HTML" for call in bot.send_message.await_args_list)


async def test_stream_receipt_preserves_original_markdown_across_overflow_and_new_stream(channel):
    metadata = {"_cron_trigger": {"run_id": "markdown-stream"}}
    parts = ["```python\n" + "print('a')\n" * 200, "print('b')\n" * 450, "print('c')\n" * 450 + "```\nDone"]
    for part in parts:
        if "7" in channel._stream_bufs:
            channel._stream_bufs["7"].last_edit = 0
        await channel.send_delta("7", part, metadata, stream_id="markdown")
    assert channel._app.bot.send_message.await_count > 2
    # A stale end must not finalize the active buffer.
    await channel.send_delta("7", "", metadata, stream_id="older", stream_end=True)
    channel.on_notification_delivered.assert_not_awaited()
    await channel.send_delta("7", "", metadata, stream_id="markdown", stream_end=True)
    text = "".join(parts)
    channel.on_notification_delivered.assert_awaited_once_with(text, notification_receipt_id(metadata, text))
    channel.on_notification_delivered.reset_mock()
    await channel.send_delta("7", "Next notification", metadata, stream_id="next")
    await channel.send_delta("7", "", metadata, stream_id="markdown", stream_end=True)
    channel.on_notification_delivered.assert_not_awaited()
    await channel.send_delta("7", "", metadata, stream_id="next", stream_end=True)
    channel.on_notification_delivered.assert_awaited_once_with(
        "Next notification", notification_receipt_id(metadata, "Next notification"),
    )


@pytest.mark.parametrize("flush_midstream", [False, True])
async def test_full_receipt_equals_confirmed_telegram_messages(channel, flush_midstream):
    delivered = {}

    async def send_message(**kwargs):
        message_id = len(delivered) + 1
        delivered[message_id] = kwargs["text"]
        return SimpleNamespace(message_id=message_id)

    async def edit_message_text(**kwargs):
        delivered[kwargs["message_id"]] = kwargs["text"]

    channel._app.bot.send_message.side_effect = send_message
    channel._app.bot.edit_message_text.side_effect = edit_message_text
    metadata = {"_cron_trigger": {"run_id": "confirmed-text"}}
    parts = [letter * 2800 for letter in "ABCDEF"]
    for part in parts:
        if "7" in channel._stream_bufs:
            channel._stream_bufs["7"].last_edit = 0 if flush_midstream else float("inf")
        await channel.send_delta("7", part, metadata, stream_id="long")
    channel.on_notification_delivered.assert_not_awaited()
    await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    text = "".join(parts)
    assert len(delivered) > 2
    assert all(len(part) <= 4096 for part in delivered.values())
    assert "".join(delivered.values()) == text
    channel.on_notification_delivered.assert_awaited_once_with(text, notification_receipt_id(metadata, text))


@pytest.mark.parametrize("failure_at", [1, 2])
async def test_failed_overflow_fragment_creates_no_receipt_or_fallback_send(channel, failure_at):
    from telegram.error import NetworkError

    from nanobot.channels.telegram.runtime import (
        TELEGRAM_HTML_MAX_LEN,
        _split_telegram_markdown_html_chunks,
    )

    metadata = {"_cron_trigger": {"run_id": "failed-overflow"}}
    await channel.send_delta("7", "A" * 2800, metadata, stream_id="long")
    channel._stream_bufs["7"].last_edit = 0
    bot = channel._app.bot
    bot.send_message.reset_mock()
    bot.send_message.side_effect = [SimpleNamespace(message_id=45)] * (failure_at - 1) + [NetworkError("fixture disconnected")]
    await channel.send_delta("7", "B" * 8000, metadata, stream_id="long")
    channel.on_notification_delivered.assert_not_awaited()
    assert bot.send_message.await_count == failure_at
    buf = channel._stream_bufs["7"]
    full_text = "A" * 2800 + "B" * 8000
    assert buf.full_text == full_text
    assert 0 < len(buf.text) <= len(full_text)
    if failure_at == 2:
        assert len(buf.text) < len(full_text)
    # Resume the unsent tail without replaying the delta or confirmed prefix.
    remaining = buf.text
    bot.send_message.side_effect = None
    bot.send_message.reset_mock()
    bot.edit_message_text.reset_mock()
    buf.last_edit = 0
    await channel.send_delta("7", "", metadata, stream_id="long")
    assert buf.full_text == full_text
    assert bot.edit_message_text.await_args.kwargs["text"] == (
        _split_telegram_markdown_html_chunks(remaining, TELEGRAM_HTML_MAX_LEN)[0][1]
    )
    await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    channel.on_notification_delivered.assert_awaited_once_with(
        full_text, notification_receipt_id(metadata, full_text),
    )


@pytest.mark.parametrize("primary_mode", ["not-modified", "plain"])
async def test_final_split_confirmation_uses_matching_markdown_chunks(channel, primary_mode):
    from telegram.error import BadRequest

    from nanobot.channels.telegram.runtime import (
        TELEGRAM_HTML_MAX_LEN,
        _split_telegram_markdown_html_chunks,
    )

    metadata = {"_cron_trigger": {"run_id": "final-markdown"}}
    text = "**bold** & " * 350
    chunks = _split_telegram_markdown_html_chunks(text, TELEGRAM_HTML_MAX_LEN)
    assert len(chunks) > 1
    await channel.send_delta("7", text[:1], metadata, stream_id="long")
    channel._stream_bufs["7"].last_edit = float("inf")
    await channel.send_delta("7", text[1:], metadata, stream_id="long")
    bot = channel._app.bot
    bot.send_message.reset_mock()
    # Each remaining chunk is explicitly rejected as HTML, then succeeds in plain text.
    bot.send_message.side_effect = [item for _ in chunks[1:] for item in (
        BadRequest("Can't parse entities"), SimpleNamespace(message_id=45),
    )]
    bot.edit_message_text.side_effect = (
        BadRequest("Message is not modified") if primary_mode == "not-modified"
        else [BadRequest("Can't parse entities"), None]
    )
    await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    if primary_mode == "not-modified":
        bot.edit_message_text.assert_awaited_once()
    else:
        assert bot.edit_message_text.await_args.kwargs["text"] == chunks[0][0]
        assert "parse_mode" not in bot.edit_message_text.await_args.kwargs
    calls = bot.send_message.await_args_list
    for index, (markdown, html) in enumerate(chunks[1:]):
        assert calls[index * 2].kwargs["text"] == html
        assert calls[index * 2 + 1].kwargs["text"] == markdown
        assert "parse_mode" not in calls[index * 2 + 1].kwargs
    channel.on_notification_delivered.assert_awaited_once_with(text, notification_receipt_id(metadata, text))


async def test_merged_stream_boundary_waits_for_final_receipt(channel):
    metadata, text = await _overflow_notification(channel)
    channel._stream_bufs["7"].last_edit = 0
    await channel.send_delta("7", "-boundary-", metadata, stream_id="long", stream_end=True, merge_next=True)
    channel.on_notification_delivered.assert_not_awaited()
    await channel.send_delta("7", "next round", metadata, stream_id="long")
    await channel.send_delta("7", "", metadata, stream_id="long", stream_end=True)
    text += "-boundary-next round"
    channel.on_notification_delivered.assert_awaited_once_with(text, notification_receipt_id(metadata, text))


@pytest.mark.parametrize("timeout_at", [None, "overflow", "final"])
async def test_rich_notification_receipt_requires_every_chunk_confirmed(channel, timeout_at):
    from telegram.error import TimedOut

    channel.config.rich_messages = True
    metadata = {"is_group": False, "_cron_trigger": {"run_id": "rich-delivery"}}
    phase = "overflow"
    sent_chunks = []

    async def api_request(method, *, api_kwargs):
        if method == "sendRichMessage":
            sent_chunks.append(api_kwargs["rich_message"]["markdown"])
            if phase == timeout_at:
                raise TimedOut("fixture ambiguous delivery")
        return True

    channel._app.bot.do_api_request.side_effect = api_request
    parts = ["A" * 20000, "B" * 20000]
    await channel.send_delta("7", parts[0], metadata, stream_id="rich")
    channel._stream_bufs["7"].last_edit = 0
    await channel.send_delta("7", parts[1], metadata, stream_id="rich")
    assert len(sent_chunks) == 1
    channel.on_notification_delivered.assert_not_awaited()
    phase = "final"
    await channel.send_delta("7", "", metadata, stream_id="rich", stream_end=True)
    assert len(sent_chunks) == 2
    assert "".join(sent_chunks) == "".join(parts)
    if timeout_at is None:
        text = "".join(parts)
        channel.on_notification_delivered.assert_awaited_once_with(
            text, notification_receipt_id(metadata, text),
        )
    else:
        channel.on_notification_delivered.assert_not_awaited()
    count = channel._app.bot.do_api_request.await_count
    await channel.send_delta("7", "", metadata, stream_id="rich", stream_end=True)
    assert channel._app.bot.do_api_request.await_count == count
    channel._app.bot.send_message.assert_not_awaited()
    assert "7" not in channel._stream_bufs
