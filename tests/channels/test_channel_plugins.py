"""Tests for channel plugin discovery, merging, and config compatibility."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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


def test_channels_config_send_max_retries_default():
    """ChannelsConfig should have send_max_retries with default value of 3."""
    cfg = ChannelsConfig()
    assert hasattr(cfg, 'send_max_retries')
    assert cfg.send_max_retries == 3


def test_channels_config_send_max_retries_upper_bound():
    """send_max_retries should be bounded to prevent resource exhaustion."""
    from pydantic import ValidationError

    # Value too high should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=100)

    # Negative should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=-1)

    # Boundary values should be allowed
    cfg_min = ChannelsConfig(send_max_retries=0)
    assert cfg_min.send_max_retries == 0

    cfg_max = ChannelsConfig(send_max_retries=10)
    assert cfg_max.send_max_retries == 10

    # Value above upper bound should be rejected
    with pytest.raises(ValidationError):
        ChannelsConfig(send_max_retries=11)


# ---------------------------------------------------------------------------
# _send_with_retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_with_retry_succeeds_first_try():
    """_send_with_retry should succeed on first try and not retry."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            # Succeeds on first try

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")
    await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 1


@pytest.mark.asyncio
async def test_send_with_retry_retries_on_failure():
    """_send_with_retry should retry on failure up to max_retries times."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    # Patch asyncio.sleep to avoid actual delays
    with patch("nanobot.channels.manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 3  # 3 total attempts (initial + 2 retries)
    assert mock_sleep.call_count == 2  # 2 sleeps between retries


@pytest.mark.asyncio
async def test_send_with_retry_no_retry_when_max_is_zero():
    """_send_with_retry should not retry when send_max_retries is 0."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=0),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    with patch("nanobot.channels.manager.asyncio.sleep", new_callable=AsyncMock):
        await mgr._send_with_retry(mgr.channels["failing"], msg)

    assert call_count == 1  # Called once but no retry (max(0, 1) = 1)


@pytest.mark.asyncio
async def test_send_with_retry_calls_send_delta():
    """_send_with_retry should call send_delta when metadata has _stream_delta."""
    send_delta_called = False

    class _StreamingChannel(BaseChannel):
        name = "streaming"
        display_name = "Streaming"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass  # Should not be called

        async def send_delta(self, chat_id: str, delta: str, metadata: dict | None = None) -> None:
            nonlocal send_delta_called
            send_delta_called = True

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"streaming": _StreamingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(
        channel="streaming", chat_id="123", content="test delta",
        metadata={"_stream_delta": True}
    )
    await mgr._send_with_retry(mgr.channels["streaming"], msg)

    assert send_delta_called is True


@pytest.mark.asyncio
async def test_send_with_retry_skips_send_when_streamed():
    """_send_with_retry should not call send when metadata has _streamed flag."""
    send_called = False
    send_delta_called = False

    class _StreamedChannel(BaseChannel):
        name = "streamed"
        display_name = "Streamed"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal send_called
            send_called = True

        async def send_delta(self, chat_id: str, delta: str, metadata: dict | None = None) -> None:
            nonlocal send_delta_called
            send_delta_called = True

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"streamed": _StreamedChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    # _streamed means message was already sent via send_delta, so skip send
    msg = OutboundMessage(
        channel="streamed", chat_id="123", content="test",
        metadata={"_streamed": True}
    )
    await mgr._send_with_retry(mgr.channels["streamed"], msg)

    assert send_called is False
    assert send_delta_called is False


@pytest.mark.asyncio
async def test_send_with_retry_propagates_cancelled_error():
    """_send_with_retry should re-raise CancelledError for graceful shutdown."""
    class _CancellingChannel(BaseChannel):
        name = "cancelling"
        display_name = "Cancelling"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            raise asyncio.CancelledError("simulated cancellation")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"cancelling": _CancellingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="cancelling", chat_id="123", content="test")

    with pytest.raises(asyncio.CancelledError):
        await mgr._send_with_retry(mgr.channels["cancelling"], msg)


@pytest.mark.asyncio
async def test_send_with_retry_propagates_cancelled_error_during_sleep():
    """_send_with_retry should re-raise CancelledError during sleep."""
    call_count = 0

    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated failure")

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(send_max_retries=3),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"failing": _FailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    msg = OutboundMessage(channel="failing", chat_id="123", content="test")

    # Mock sleep to raise CancelledError
    async def cancel_during_sleep(_):
        raise asyncio.CancelledError("cancelled during sleep")

    with patch("nanobot.channels.manager.asyncio.sleep", side_effect=cancel_during_sleep):
        with pytest.raises(asyncio.CancelledError):
            await mgr._send_with_retry(mgr.channels["failing"], msg)

    # Should have attempted once before sleep was cancelled
    assert call_count == 1


# ---------------------------------------------------------------------------
# ChannelManager - lifecycle and getters
# ---------------------------------------------------------------------------

class _ChannelWithAllowFrom(BaseChannel):
    """Channel with configurable allow_from."""
    name = "withallow"
    display_name = "With Allow"

    def __init__(self, config, bus, allow_from):
        super().__init__(config, bus)
        self.config.allow_from = allow_from

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass


class _StartableChannel(BaseChannel):
    """Channel that tracks start/stop calls."""
    name = "startable"
    display_name = "Startable"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(self, msg: OutboundMessage) -> None:
        pass


@pytest.mark.asyncio
async def test_validate_allow_from_raises_on_empty_list():
    """_validate_allow_from should raise SystemExit when allow_from is empty list."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _ChannelWithAllowFrom(fake_config, None, [])}
    mgr._dispatch_task = None

    with pytest.raises(SystemExit) as exc_info:
        mgr._validate_allow_from()

    assert "empty allowFrom" in str(exc_info.value)


@pytest.mark.asyncio
async def test_validate_allow_from_passes_with_asterisk():
    """_validate_allow_from should not raise when allow_from contains '*'."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.channels = {"test": _ChannelWithAllowFrom(fake_config, None, ["*"])}
    mgr._dispatch_task = None

    # Should not raise
    mgr._validate_allow_from()


@pytest.mark.asyncio
async def test_get_channel_returns_channel_if_exists():
    """get_channel should return the channel if it exists."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"telegram": _StartableChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    assert mgr.get_channel("telegram") is not None
    assert mgr.get_channel("nonexistent") is None


@pytest.mark.asyncio
async def test_get_status_returns_running_state():
    """get_status should return enabled and running state for each channel."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}
    mgr._dispatch_task = None

    status = mgr.get_status()

    assert status["startable"]["enabled"] is True
    assert status["startable"]["running"] is False  # Not started yet


@pytest.mark.asyncio
async def test_enabled_channels_returns_channel_names():
    """enabled_channels should return list of enabled channel names."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {
        "telegram": _StartableChannel(fake_config, mgr.bus),
        "slack": _StartableChannel(fake_config, mgr.bus),
    }
    mgr._dispatch_task = None

    enabled = mgr.enabled_channels

    assert "telegram" in enabled
    assert "slack" in enabled
    assert len(enabled) == 2


@pytest.mark.asyncio
async def test_stop_all_cancels_dispatcher_and_stops_channels():
    """stop_all should cancel the dispatch task and stop all channels."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()

    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}

    # Create a real cancelled task
    async def dummy_task():
        while True:
            await asyncio.sleep(1)

    dispatch_task = asyncio.create_task(dummy_task())
    mgr._dispatch_task = dispatch_task

    await mgr.stop_all()

    # Task should be cancelled
    assert dispatch_task.cancelled()
    # Channel should be stopped
    assert ch.stopped is True


@pytest.mark.asyncio
async def test_start_channel_logs_error_on_failure():
    """_start_channel should log error when channel start fails."""
    class _FailingChannel(BaseChannel):
        name = "failing"
        display_name = "Failing"

        async def start(self) -> None:
            raise RuntimeError("connection failed")

        async def stop(self) -> None:
            pass

        async def send(self, msg: OutboundMessage) -> None:
            pass

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}
    mgr._dispatch_task = None

    ch = _FailingChannel(fake_config, mgr.bus)

    # Should not raise, just log error
    await mgr._start_channel("failing", ch)


@pytest.mark.asyncio
async def test_stop_all_handles_channel_exception():
    """stop_all should handle exceptions when stopping channels gracefully."""
    class _StopFailingChannel(BaseChannel):
        name = "stopfailing"
        display_name = "Stop Failing"

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            raise RuntimeError("stop failed")

        async def send(self, msg: OutboundMessage) -> None:
            pass

    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {"stopfailing": _StopFailingChannel(fake_config, mgr.bus)}
    mgr._dispatch_task = None

    # Should not raise even if channel.stop() raises
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_start_all_no_channels_logs_warning():
    """start_all should log warning when no channels are enabled."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()
    mgr.channels = {}  # No channels
    mgr._dispatch_task = None

    # Should return early without creating dispatch task
    await mgr.start_all()

    assert mgr._dispatch_task is None


@pytest.mark.asyncio
async def test_start_all_creates_dispatch_task():
    """start_all should create the dispatch task when channels exist."""
    fake_config = SimpleNamespace(
        channels=ChannelsConfig(),
        providers=SimpleNamespace(groq=SimpleNamespace(api_key="")),
    )

    mgr = ChannelManager.__new__(ChannelManager)
    mgr.config = fake_config
    mgr.bus = MessageBus()

    ch = _StartableChannel(fake_config, mgr.bus)
    mgr.channels = {"startable": ch}
    mgr._dispatch_task = None

    # Cancel immediately after start to avoid running forever
    async def cancel_after_start():
        await asyncio.sleep(0.01)
        if mgr._dispatch_task:
            mgr._dispatch_task.cancel()

    cancel_task = asyncio.create_task(cancel_after_start())

    try:
        await mgr.start_all()
    except asyncio.CancelledError:
        pass
    finally:
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass

    # Dispatch task should have been created
    assert mgr._dispatch_task is not None

