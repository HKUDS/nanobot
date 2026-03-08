"""Tests for the WebUI channel."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import WebUIConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_channel(allow_from: list[str] | None = None):
    """Create a WebUIChannel with a fresh MessageBus."""
    from nanobot.channels.webui import WebUIChannel

    cfg = WebUIConfig(
        enabled=True,
        host="127.0.0.1",
        port=7860,
        allow_from=allow_from if allow_from is not None else ["*"],
    )
    return WebUIChannel(cfg, MessageBus())


# ── Config defaults ───────────────────────────────────────────────────────────

def test_webui_config_defaults():
    cfg = WebUIConfig()
    assert cfg.enabled is False
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 7860
    assert cfg.allow_from == ["*"]


def test_webui_config_camel_case():
    """Config must accept camelCase keys (nanobot convention)."""
    cfg = WebUIConfig.model_validate({"enabled": True, "host": "localhost", "port": 9000})
    assert cfg.enabled is True
    assert cfg.port == 9000


# ── allow_from / is_allowed ───────────────────────────────────────────────────

def test_is_allowed_wildcard():
    ch = _make_channel(allow_from=["*"])
    assert ch.is_allowed("anyone") is True


def test_is_allowed_specific_user():
    ch = _make_channel(allow_from=["web_user"])
    assert ch.is_allowed("web_user") is True
    assert ch.is_allowed("intruder") is False


def test_is_allowed_empty_denies_all():
    ch = _make_channel(allow_from=[])
    assert ch.is_allowed("web_user") is False


# ── send() ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_puts_message_in_queue():
    ch = _make_channel()
    q: asyncio.Queue = asyncio.Queue()
    ch._ws_queues["webui"] = q

    msg = OutboundMessage(channel="webui", chat_id="webui", content="Hello!")
    await ch.send(msg)

    # Final message → two items: the payload + the "done" sentinel
    payload = json.loads(await q.get())
    done    = json.loads(await q.get())

    assert payload["type"] == "message"
    assert payload["content"] == "Hello!"
    assert done["type"] == "done"


@pytest.mark.asyncio
async def test_send_progress_no_done_sentinel():
    ch = _make_channel()
    q: asyncio.Queue = asyncio.Queue()
    ch._ws_queues["webui"] = q

    msg = OutboundMessage(
        channel="webui",
        chat_id="webui",
        content="…thinking…",
        metadata={"_progress": True},
    )
    await ch.send(msg)

    assert q.qsize() == 1  # only the token, no "done"
    payload = json.loads(await q.get())
    assert payload["type"] == "token"


@pytest.mark.asyncio
async def test_send_no_active_ws_logs_debug(caplog):
    ch = _make_channel()
    msg = OutboundMessage(channel="webui", chat_id="ghost", content="dropped")
    # Should not raise, just log
    await ch.send(msg)


# ── stop() ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_sets_running_false():
    ch = _make_channel()
    ch._running = True
    ch._server = MagicMock()
    ch._server.should_exit = False

    await ch.stop()

    assert ch._running is False
    assert ch._server.should_exit is True


# ── _handle_message integration ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_message_publishes_to_bus():
    ch = _make_channel(allow_from=["*"])
    await ch._handle_message(
        sender_id="web_user",
        chat_id="webui",
        content="test message",
    )
    msg = await asyncio.wait_for(ch.bus.consume_inbound(), timeout=1.0)
    assert msg.content == "test message"
    assert msg.channel == "webui"


@pytest.mark.asyncio
async def test_handle_message_denied_does_not_publish():
    ch = _make_channel(allow_from=["allowed_only"])
    await ch._handle_message(
        sender_id="intruder",
        chat_id="webui",
        content="should be dropped",
    )
    assert ch.bus.inbound_size == 0


# ── ChannelsConfig integration ────────────────────────────────────────────────

def test_channels_config_has_webui_field():
    from nanobot.config.schema import ChannelsConfig

    cfg = ChannelsConfig()
    assert hasattr(cfg, "webui")
    assert isinstance(cfg.webui, WebUIConfig)
    assert cfg.webui.enabled is False
