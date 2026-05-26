"""Tests for Feishu group message buffering."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from nanobot.channels import feishu

    FEISHU_AVAILABLE = getattr(feishu, "FEISHU_AVAILABLE", False)
except ImportError:
    FEISHU_AVAILABLE = False

if not FEISHU_AVAILABLE:
    pytest.skip("Feishu dependencies not installed (lark-oapi)", allow_module_level=True)

from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu import FeishuChannel, FeishuConfig


def _make_feishu_channel() -> FeishuChannel:
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
        group_policy="open",
        group_debounce_seconds=0.02,
        topic_isolation=False,
    )
    channel = FeishuChannel(config, MessageBus())
    channel._client = MagicMock()
    channel._loop = None
    return channel


def _make_feishu_event(*, message_id: str, text: str) -> SimpleNamespace:
    message = SimpleNamespace(
        message_id=message_id,
        chat_id="oc_group",
        chat_type="group",
        message_type="text",
        content=json.dumps({"text": text}),
        parent_id=None,
        root_id=None,
        mentions=[],
    )
    sender = SimpleNamespace(
        sender_type="user",
        sender_id=SimpleNamespace(open_id="ou_alice"),
    )
    return SimpleNamespace(event=SimpleNamespace(message=message, sender=sender))


@pytest.mark.asyncio
async def test_group_messages_are_debounced_into_one_turn() -> None:
    channel = _make_feishu_channel()
    channel._handle_message = AsyncMock()
    channel._schedule_reaction = lambda _message_id: None

    await channel._on_message(_make_feishu_event(message_id="om_1", text="first"))
    await channel._on_message(_make_feishu_event(message_id="om_2", text="second"))
    await asyncio.sleep(0.05)

    channel._handle_message.assert_awaited_once()
    call_kwargs = channel._handle_message.await_args.kwargs
    assert call_kwargs["content"] == "first\nsecond"
    assert call_kwargs["metadata"]["group_buffered"] is True
    assert call_kwargs["metadata"]["group_buffered_count"] == 2
    assert call_kwargs["metadata"]["group_buffered_message_ids"] == ["om_1", "om_2"]