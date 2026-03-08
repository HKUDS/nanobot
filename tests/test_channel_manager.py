"""Tests for channel manager dispatch and lifecycle behavior."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager


def _disabled_channels() -> SimpleNamespace:
    return SimpleNamespace(
        telegram=SimpleNamespace(enabled=False),
        whatsapp=SimpleNamespace(enabled=False),
        discord=SimpleNamespace(enabled=False),
        feishu=SimpleNamespace(enabled=False),
        mochat=SimpleNamespace(enabled=False),
        dingtalk=SimpleNamespace(enabled=False),
        email=SimpleNamespace(enabled=False),
        slack=SimpleNamespace(enabled=False),
        qq=SimpleNamespace(enabled=False),
    )


def _minimal_config() -> SimpleNamespace:
    return SimpleNamespace(
        channels=_disabled_channels(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )


class FakeChannel:
    """Minimal async fake channel for manager tests."""

    def __init__(self, fail_send: bool = False) -> None:
        self.fail_send = fail_send
        self.start_calls = 0
        self.stop_calls = 0
        self.send_calls = 0
        self.sent: list[OutboundMessage] = []
        self.is_running = False

    async def start(self) -> None:
        self.start_calls += 1
        self.is_running = True

    async def stop(self) -> None:
        self.stop_calls += 1
        self.is_running = False

    async def send(self, msg: OutboundMessage) -> None:
        self.send_calls += 1
        if self.fail_send:
            raise RuntimeError("send failed")
        self.sent.append(msg)


@pytest.mark.asyncio
async def test_dispatch_outbound_routes_messages_and_survives_send_errors(monkeypatch) -> None:
    """Routes outbound messages to channels and continues after send failures."""
    monkeypatch.setattr(ChannelManager, "_init_channels", lambda self: None)
    bus = MessageBus()
    manager = ChannelManager(_minimal_config(), bus)
    ok_channel = FakeChannel()
    failing_channel = FakeChannel(fail_send=True)
    manager.channels = {"ok": ok_channel, "bad": failing_channel}

    task = asyncio.create_task(manager._dispatch_outbound())
    await bus.publish_outbound(OutboundMessage(channel="ok", chat_id="c1", content="a"))
    await bus.publish_outbound(OutboundMessage(channel="bad", chat_id="c1", content="b"))
    await bus.publish_outbound(OutboundMessage(channel="unknown", chat_id="c1", content="c"))
    await asyncio.sleep(0.05)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(ok_channel.sent) == 1
    assert ok_channel.sent[0].content == "a"
    assert failing_channel.send_calls == 1


@pytest.mark.asyncio
async def test_start_all_and_stop_all_manage_dispatcher_and_channels(monkeypatch) -> None:
    """Starts channels with dispatcher task and stops all cleanly."""
    monkeypatch.setattr(ChannelManager, "_init_channels", lambda self: None)
    started = asyncio.Event()

    async def _fake_dispatch_outbound(self: ChannelManager) -> None:
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ChannelManager, "_dispatch_outbound", _fake_dispatch_outbound)
    bus = MessageBus()
    manager = ChannelManager(_minimal_config(), bus)
    first = FakeChannel()
    second = FakeChannel()
    manager.channels = {"one": first, "two": second}

    await manager.start_all()
    assert started.is_set()
    assert manager._dispatch_task is not None
    assert first.start_calls == 1
    assert second.start_calls == 1

    await manager.stop_all()
    assert first.stop_calls == 1
    assert second.stop_calls == 1


@pytest.mark.asyncio
async def test_init_channels_uses_monkeypatched_module_imports(monkeypatch) -> None:
    """Builds enabled channel from monkeypatched module without external imports."""
    bus = MessageBus()
    config = _minimal_config()
    config.channels.telegram.enabled = True

    class _TelegramFake(FakeChannel):
        def __init__(self, _cfg: SimpleNamespace, _bus: MessageBus, groq_api_key: str) -> None:
            super().__init__()
            self.groq_api_key = groq_api_key

    fake_module = SimpleNamespace(TelegramChannel=_TelegramFake)
    monkeypatch.setitem(sys.modules, "nanobot.channels.telegram", fake_module)

    manager = ChannelManager(config, bus)

    assert "telegram" in manager.channels
    assert isinstance(manager.channels["telegram"], _TelegramFake)
