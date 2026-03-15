from __future__ import annotations

import asyncio
import json
import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import Config


def _install_fake_channel_module(monkeypatch: pytest.MonkeyPatch, mod_name: str, class_name: str):
    mod = ModuleType(mod_name)

    class _Ch:
        def __init__(self, *args, **kwargs):
            self.is_running = True
            self.start = AsyncMock()
            self.stop = AsyncMock()

    setattr(mod, class_name, _Ch)
    monkeypatch.setitem(sys.modules, mod_name, mod)


@pytest.mark.asyncio
async def test_init_channels_and_start_all(monkeypatch: pytest.MonkeyPatch, tmp_path):
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    cfg.channels.telegram.enabled = True
    cfg.channels.whatsapp.enabled = True
    cfg.channels.discord.enabled = True
    cfg.channels.email.enabled = True
    cfg.channels.slack.enabled = True

    _install_fake_channel_module(monkeypatch, "nanobot.channels.telegram", "TelegramChannel")
    _install_fake_channel_module(monkeypatch, "nanobot.channels.whatsapp", "WhatsAppChannel")
    _install_fake_channel_module(monkeypatch, "nanobot.channels.discord", "DiscordChannel")
    _install_fake_channel_module(monkeypatch, "nanobot.channels.email", "EmailChannel")
    _install_fake_channel_module(monkeypatch, "nanobot.channels.slack", "SlackChannel")

    bus = object()
    mgr = ChannelManager(cfg, bus)
    assert len(mgr.channels) == 5

    # Dead-letter auto-replay path
    dead = tmp_path / "outbound_failed.jsonl"
    dead.write_text(
        json.dumps({"channel": "telegram", "chat_id": "1", "content": "x"}) + "\n", encoding="utf-8"
    )
    mgr._dead_letter_file = dead
    mgr.replay_dead_letters = AsyncMock(return_value=(1, 1, 0))  # type: ignore[method-assign]

    # Keep dispatcher from looping forever.
    async def _dispatch_once():
        await asyncio.sleep(0)

    mgr._dispatch_outbound = _dispatch_once  # type: ignore[method-assign]

    await mgr.start_all()
    assert mgr.replay_dead_letters.await_count == 1

    await mgr.stop_all()


def test_init_channels_import_error_branch(monkeypatch: pytest.MonkeyPatch, tmp_path):
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    cfg.channels.telegram.enabled = True

    import builtins

    orig_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == "nanobot.channels.telegram":
            raise ImportError("forced")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)

    mgr = ChannelManager(cfg, object())
    assert "telegram" not in mgr.channels
