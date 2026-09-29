"""QQ drops compaction notices it cannot present as one message.

QQ's C2C/group message API has no edit or recall endpoint, so the
compaction lifecycle would land as two separate permanent messages. The
channel drops automatic notices by default; ``showCompactionNotices: true``
restores them (#5784). Manual requests keep their feedback independently.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytest.importorskip("botpy")

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ContextCompactionEvent, outbound_message_for_event
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq.runtime import QQChannel, QQConfig


def _make_channel(tmp_path, **config_kwargs) -> QQChannel:
    config = QQConfig(
        app_id="test_app", secret="test_secret", media_dir=str(tmp_path), **config_kwargs,
    )
    channel = QQChannel(config, MessageBus())
    channel._client = object()  # truthy: pass the initialized check
    return channel


@pytest.mark.asyncio
async def test_compaction_notices_dropped_by_default(monkeypatch, tmp_path) -> None:
    channel = _make_channel(tmp_path)
    send_text = AsyncMock()
    monkeypatch.setattr(channel, "_send_text_only", send_text)

    for phase in ("started", "succeeded"):
        await channel.send(outbound_message_for_event(
            channel="qq", chat_id="chat",
            event=ContextCompactionEvent(compaction_id="c1", phase=phase),
        ))

    send_text.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("notify", [False, True])
@pytest.mark.parametrize("phase", ["started", "succeeded", "failed", "cancelled"])
async def test_compaction_notices_sent_when_enabled(monkeypatch, tmp_path, notify, phase) -> None:
    channel = _make_channel(tmp_path, show_compaction_notices=True)
    send_text = AsyncMock()
    monkeypatch.setattr(channel, "_send_text_only", send_text)

    await channel.send(outbound_message_for_event(
        channel="qq", chat_id="chat",
        event=ContextCompactionEvent(compaction_id="c1", phase=phase, notify=notify),
    ))

    send_text.assert_awaited_once()
    assert send_text.await_args.kwargs["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["started", "succeeded", "failed", "cancelled"])
async def test_manual_compaction_has_feedback_with_default_config(monkeypatch, tmp_path, phase) -> None:
    channel = _make_channel(tmp_path)
    send_text = AsyncMock()
    monkeypatch.setattr(channel, "_send_text_only", send_text)

    await channel.send(outbound_message_for_event(
        channel="qq", chat_id="chat",
        event=ContextCompactionEvent(compaction_id="manual", phase=phase, notify=True),
    ))

    send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_ordinary_messages_unaffected(monkeypatch, tmp_path) -> None:
    channel = _make_channel(tmp_path)
    send_text = AsyncMock()
    monkeypatch.setattr(channel, "_send_text_only", send_text)

    await channel.send(OutboundMessage(channel="qq", chat_id="chat", content="hello"))

    send_text.assert_awaited_once()


def test_config_accepts_camel_case_override() -> None:
    config = QQConfig.model_validate({"appId": "a", "secret": "s", "showCompactionNotices": True})
    assert config.show_compaction_notices is True
