"""Tests for channel plugin discovery, merging, and config compatibility."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.config.schema import ChannelsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakePlugin(BaseChannel):
    name = "fakeplugin"
    display_name = "Fake Plugin"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.login_calls: list[bool] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass

    async def login(self, force: bool = False) -> bool:
        self.login_calls.append(force)
        return True


class _FakeTelegram(BaseChannel):
    """Plugin that tries to shadow built-in telegram."""
    name = "telegram"
    display_name = "Fake Telegram"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


def _make_entry_point(name: str, cls: type):
    """Create a mock entry point that returns *cls* on load()."""
    ep = SimpleNamespace(name=name, load=lambda _cls=cls: _cls)
    return ep


# ---------------------------------------------------------------------------
# ChannelsConfig extra="allow"
# ---------------------------------------------------------------------------

def test_channels_config_accepts_unknown_keys():
    cfg = ChannelsConfig.model_validate({
        "myplugin": {"enabled": True, "token": "abc"},
    })
    extra = cfg.model_extra
    assert extra is not None
    assert extra["myplugin"]["enabled"] is True
    assert extra["myplugin"]["token"] == "abc"


def test_channels_config_getattr_returns_extra():
    cfg = ChannelsConfig.model_validate({"myplugin": {"enabled": True}})
    section = getattr(cfg, "myplugin", None)
    assert isinstance(section, dict)
    assert section["enabled"] is True


def test_channels_config_builtin_fields_removed():
    """After decoupling, ChannelsConfig has no explicit channel fields."""
    cfg = ChannelsConfig()
    assert not hasattr(cfg, "telegram")
    assert cfg.send_progress is True
    assert cfg.send_tool_hints is False


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------

_EP_TARGET = "importlib.metadata.entry_points"


def test_discover_plugins_loads_entry_points():
    from nanobot.channels.registry import discover_plugins

    ep = _make_entry_point("line", _FakePlugin)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_plugins()

    assert "line" in result
    assert result["line"] is _FakePlugin


def test_discover_plugins_handles_load_error():
    from nanobot.channels.registry import discover_plugins

    def _boom():
        raise RuntimeError("broken")

    ep = SimpleNamespace(name="broken", load=_boom)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_plugins()

    assert "broken" not in result


# ---------------------------------------------------------------------------
# discover_all — merge & priority
# ---------------------------------------------------------------------------

def test_discover_all_includes_builtins():
    from nanobot.channels.registry import discover_all, discover_channel_names

    with patch(_EP_TARGET, return_value=[]):
        result = discover_all()

    # discover_all() only returns channels that are actually available (dependencies installed)
    # discover_channel_names() returns all built-in channel names
    # So we check that all actually loaded channels are in the result
    for name in result:
        assert name in discover_channel_names()


def test_discover_all_includes_external_plugin():
    from nanobot.channels.registry import discover_all

    ep = _make_entry_point("line", _FakePlugin)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_all()

    assert "line" in result
    assert result["line"] is _FakePlugin


def test_discover_all_builtin_shadows_plugin():
    from nanobot.channels.registry import discover_all

    ep = _make_entry_point("telegram", _FakeTelegram)
    with patch(_EP_TARGET, return_value=[ep]):
        result = discover_all()

    assert "telegram" in result
    assert result["telegram"] is not _FakeTelegram


# ---------------------------------------------------------------------------
# Manager _init_channels with dict config (plugin scenario)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_loads_plugin_from_dict_config():
    """ChannelManager should instantiate a plugin channel from a raw dict config."""
    from nanobot.channels.manager import ChannelManager

    fake_config = SimpleNamespace(
        channels=ChannelsConfig.model_validate({
            "fakeplugin": {"enabled": True, "allowFrom": ["*"]},
        }),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key=""), dashscope=SimpleNamespace(api_key="")),
        tools=SimpleNamespace(transcription=SimpleNamespace(provider="groq", api_key="")),
    )

    with patch(
        "nanobot.channels.registry.discover_all",
        return_value={"fakeplugin": _FakePlugin},
    ):
        mgr = ChannelManager.__new__(ChannelManager)
        mgr.config = fake_config
        mgr.bus = MessageBus()
        mgr.channels = {}
        mgr._dispatch_task = None
        mgr._init_channels()

    assert "fakeplugin" in mgr.channels
    assert isinstance(mgr.channels["fakeplugin"], _FakePlugin)


def test_channels_login_uses_discovered_plugin_class(monkeypatch):
    from nanobot.cli.commands import app
    from nanobot.config.schema import Config
    from typer.testing import CliRunner

    runner = CliRunner()
    seen: dict[str, object] = {}

    class _LoginPlugin(_FakePlugin):
        display_name = "Login Plugin"

        async def login(self, force: bool = False) -> bool:
            seen["force"] = force
            seen["config"] = self.config
            return True

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: Config())
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: {"fakeplugin": _LoginPlugin},
    )

    result = runner.invoke(app, ["channels", "login", "fakeplugin", "--force"])

    assert result.exit_code == 0
    assert seen["force"] is True


@pytest.mark.asyncio
async def test_manager_skips_disabled_plugin():
    fake_config = SimpleNamespace(
        channels=ChannelsConfig.model_validate({
            "fakeplugin": {"enabled": False},
        }),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key=""), dashscope=SimpleNamespace(api_key="")),
        tools=SimpleNamespace(transcription=SimpleNamespace(provider="groq", api_key="")),
    )

    with patch(
        "nanobot.channels.registry.discover_all",
        return_value={"fakeplugin": _FakePlugin},
    ):
        mgr = ChannelManager.__new__(ChannelManager)
        mgr.config = fake_config
        mgr.bus = MessageBus()
        mgr.channels = {}
        mgr._dispatch_task = None
        mgr._init_channels()

    assert "fakeplugin" not in mgr.channels


# ---------------------------------------------------------------------------
# Built-in channel default_config() and dict->Pydantic conversion
# ---------------------------------------------------------------------------

def test_builtin_channel_default_config():
    """Built-in channels expose default_config() returning a dict with 'enabled': False."""
    from nanobot.channels.telegram import TelegramChannel
    cfg = TelegramChannel.default_config()
    assert isinstance(cfg, dict)
    assert cfg["enabled"] is False
    assert "token" in cfg


def test_builtin_channel_init_from_dict():
    """Built-in channels accept a raw dict and convert to Pydantic internally."""
    from nanobot.channels.telegram import TelegramChannel
    bus = MessageBus()
    ch = TelegramChannel({"enabled": False, "token": "test-tok", "allowFrom": ["*"]}, bus)
    assert ch.config.token == "test-tok"
    assert ch.config.allow_from == ["*"]
