"""QQ drops compaction notices it cannot present as one message.

QQ's C2C/group message API has no edit or recall endpoint, so the
compaction lifecycle would land as two separate permanent messages. The
channel drops ``ContextCompactionEvent`` by default; ``showCompactionNotices:
true`` restores the notices for anyone who wants them (#5784).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytest.importorskip("botpy")

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ContextCompactionEvent, outbound_message_for_event
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq.runtime import QQChannel, QQConfig


def _make_channel(**config_kwargs) -> QQChannel:
    config = QQConfig(app_id="test_app", secret="test_secret", **config_kwargs)
    channel = QQChannel(config, MessageBus())
    channel._client = object()  # truthy: pass the initialized check
    return channel


@pytest.mark.asyncio
async def test_compaction_notices_dropped_by_default(monkeypatch) -> None:
    channel = _make_channel()
    send_text = AsyncMock()
    monkeypatch.setattr(channel, "_send_text_only", send_text)

    for phase in ("started", "succeeded"):
        await channel.send(outbound_message_for_event(
            channel="qq", chat_id="chat",
            event=ContextCompactionEvent(compaction_id="c1", phase=phase),
        ))

    send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_compaction_notices_sent_when_enabled(monkeypatch) -> None:
    channel = _make_channel(show_compaction_notices=True)
    send_text = AsyncMock()
    monkeypatch.setattr(channel, "_send_text_only", send_text)

    await channel.send(outbound_message_for_event(
        channel="qq", chat_id="chat",
        event=ContextCompactionEvent(compaction_id="c1", phase="started"),
    ))

    send_text.assert_awaited_once()
    assert send_text.await_args.kwargs["content"] == "Compressing context…"


@pytest.mark.asyncio
async def test_ordinary_messages_unaffected(monkeypatch) -> None:
    channel = _make_channel()
    send_text = AsyncMock()
    monkeypatch.setattr(channel, "_send_text_only", send_text)

    await channel.send(OutboundMessage(channel="qq", chat_id="chat", content="hello"))

    send_text.assert_awaited_once()


def test_config_accepts_camel_case_override() -> None:
    config = QQConfig.model_validate({"appId": "a", "secret": "s", "showCompactionNotices": True})
    assert config.show_compaction_notices is True
