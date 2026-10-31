from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.manager import ChannelManager
from nanobot.channels.registry import load_channel_plugin
from nanobot.channels.whatsapp.runtime import WhatsAppChannel
from nanobot.config.network import NetworkConfig
from nanobot.config.schema import Config

_CHANNEL_VALUES = {
    "telegram": {"token": "123456:abcdefghijklmnopqrstuvwxyz"},
    "discord": {"token": "discord-token"},
    "slack": {"appToken": "xapp-test", "botToken": "xoxb-test"},
    "matrix": {
        "homeserver": "https://matrix.example",
        "userId": "@bot:matrix.example",
        "password": "matrix-password",
    },
    "whatsapp": {"enabled": True},
}


@pytest.mark.parametrize("name", _CHANNEL_VALUES)
def test_setup_refuses_proxy_opt_in_without_shared_address(name, monkeypatch) -> None:
    def fail_client(*_args, **_kwargs):
        pytest.fail("missing shared proxy must not fall back to a direct connection")

    monkeypatch.setattr("httpx.Client", fail_client)
    validator = load_channel_plugin(name).setup.validator

    result = validator(
        {**_CHANNEL_VALUES[name], "useProxy": True}, ChannelValidationContext(),
    )

    assert result["status"] == "invalid"
    assert result["can_enable"] is False
    proxy_check = next(check for check in result["checks"] if check["id"] == "network_proxy")
    assert proxy_check["status"] == "fail"
    assert "Advanced" in proxy_check["message"]


@pytest.mark.parametrize(
    ("name", "request_method", "response"),
    [
        ("telegram", "_get_me", {"ok": True, "result": {"id": 42}}),
        ("discord", "http_get", {"id": "42", "username": "bot"}),
        ("slack", "http_post", {"ok": True, "user_id": "U42"}),
    ],
)
@pytest.mark.parametrize("use_proxy", [True, False, "false"])
def test_identity_validation_respects_shared_proxy_opt_in(
    name, request_method, response, use_proxy, monkeypatch,
) -> None:
    module = importlib.import_module(f"nanobot.channels.{name}.validation")
    proxies = []

    def request(_target, proxy=None, **_kwargs):
        proxies.append(proxy)
        return response

    monkeypatch.setattr(module, request_method, request)
    network = NetworkConfig(proxy="http://user:pass@127.0.0.1:7890")

    result = module.validate(
        {**_CHANNEL_VALUES[name], "useProxy": use_proxy},
        ChannelValidationContext(network=network),
    )

    assert result["status"] == "connected"
    assert proxies == [network.proxy if use_proxy is True else None]
    assert network.proxy not in str(result)


@pytest.mark.parametrize("name", _CHANNEL_VALUES)
def test_runtime_refuses_proxy_opt_in_without_shared_address(name) -> None:
    pytest.importorskip(f"nanobot.channels.{name}.runtime", exc_type=ImportError)
    channel_cls = load_channel_plugin(name).load_channel_class()

    with pytest.raises(ValueError, match="Advanced"):
        channel_cls({"useProxy": True}, MessageBus(), network=NetworkConfig())


@pytest.mark.parametrize("name", _CHANNEL_VALUES)
@pytest.mark.parametrize("use_proxy", [True, False])
def test_manager_constructs_proxy_capable_builtin_from_descriptor(
    name, use_proxy, monkeypatch, tmp_path,
) -> None:
    pytest.importorskip(f"nanobot.channels.{name}.runtime", exc_type=ImportError)
    plugin = load_channel_plugin(name)
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda: {name: plugin})
    monkeypatch.setattr("nanobot.optional_features.extra_installed", lambda *_args: True)
    config = Config.model_validate({
        "network": {"proxy": "http://127.0.0.1:7890"},
        "channels": {
            name: {**_CHANNEL_VALUES[name], "enabled": True, "useProxy": use_proxy},
        },
    })

    manager = ChannelManager(config, MessageBus(), config_path=tmp_path / "config.json")

    channel = manager.channels[name]
    assert isinstance(channel, plugin.load_channel_class())
    assert channel.uses_shared_proxy is True
    assert channel.network is config.network
    assert channel._proxy == (config.network.proxy if use_proxy else None)


@pytest.mark.asyncio
async def test_manager_keeps_shared_proxy_instance_scoped(monkeypatch) -> None:
    class ProxySettings:
        def __init__(self, *, proxy_address: str) -> None:
            self.proxy_address = proxy_address

    monkeypatch.setitem(sys.modules, "neonize._binder", SimpleNamespace(ProxySettings=ProxySettings))
    channels = []
    for address in ("http://127.0.0.1:7890", "http://127.0.0.1:7891"):
        manager = object.__new__(ChannelManager)
        manager.config = Config(network=NetworkConfig(proxy=address))
        manager.bus = MessageBus()
        channel = manager._build_channel(WhatsAppChannel, {"useProxy": True})
        assert channel.network is manager.config.network
        channels.append(channel)

    for channel, address in zip(channels, ("http://127.0.0.1:7890", "http://127.0.0.1:7891")):
        client = SimpleNamespace(connect=AsyncMock())
        await channel._connect_client(client)
        assert client.connect.await_args.args[0].proxy_address == address
        assert channel.config.model_dump(by_alias=True)["useProxy"] is True
        assert "proxy" not in channel.config.model_dump(by_alias=True)


@pytest.mark.parametrize(("name", "request_method"), [("discord", "http_get"), ("slack", "http_post")])
def test_identity_validation_does_not_expose_shared_proxy_in_errors(name, request_method, monkeypatch) -> None:
    module = importlib.import_module(f"nanobot.channels.{name}.validation")
    network = NetworkConfig(proxy="http://user:pass@127.0.0.1:7890")

    def fail_request(*_args, **_kwargs):
        raise OSError(f"could not connect through {network.proxy}")

    monkeypatch.setattr(module, request_method, fail_request)
    result = module.validate(
        {**_CHANNEL_VALUES[name], "useProxy": True}, ChannelValidationContext(network=network),
    )

    assert result["status"] == "configured"
    assert result["can_enable"] is True
    assert any(check["status"] == "warn" for check in result["checks"])
    assert network.proxy not in str(result)
    assert "user:pass" not in str(result)
