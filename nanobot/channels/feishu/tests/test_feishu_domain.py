"""Tests for Feishu/Lark domain configuration."""
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu.runtime import FeishuChannel, FeishuConfig


def _make_channel(domain: str = "feishu") -> FeishuChannel:
    config = FeishuConfig(
        enabled=True,
        app_id="cli_test",
        app_secret="secret",
        allow_from=["*"],
        domain=domain,
    )
    ch = FeishuChannel(config, MessageBus())
    ch._client = MagicMock()
    ch._loop = None
    return ch


class TestFeishuConfigDomain:
    def test_domain_default_is_feishu(self):
        config = FeishuConfig()
        assert config.domain == "feishu"

    def test_domain_accepts_lark(self):
        config = FeishuConfig(domain="lark")
        assert config.domain == "lark"

    def test_domain_accepts_feishu(self):
        config = FeishuConfig(domain="feishu")
        assert config.domain == "feishu"

    def test_default_config_includes_domain(self):
        default_cfg = FeishuChannel.default_config()
        assert "domain" in default_cfg
        assert default_cfg["domain"] == "feishu"

    def test_channel_persists_domain_from_config(self):
        ch = _make_channel(domain="lark")
        assert ch.config.domain == "lark"

    def test_channel_persists_feishu_domain_from_config(self):
        ch = _make_channel(domain="feishu")
        assert ch.config.domain == "feishu"


@pytest.mark.asyncio
@pytest.mark.parametrize("domain, expected_domain", [
    ("feishu", "https://open.feishu.cn"),
    ("lark", "https://open.larksuite.com"),
])
async def test_start_selects_domain_for_http_and_websocket_sdk_clients(
    domain, expected_domain, monkeypatch, tmp_path,
):
    lark = pytest.importorskip("lark_oapi")
    # Startup must never persist fixture credentials into the active host config.
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(
        "nanobot.channels.feishu.runtime.sync_saved_feishu_identity_boundary",
        lambda **_kwargs: False,
    )
    builder = MagicMock()
    for method in ("app_id", "app_secret", "domain", "log_level"):
        getattr(builder, method).return_value = builder
    monkeypatch.setattr(lark.Client, "builder", lambda: builder)
    ws_client = MagicMock()
    monkeypatch.setattr(lark.ws, "Client", ws_client)
    ch = _make_channel(domain)

    async def started(*_args):
        ch._running = False

    # Keep production start/domain selection, but never open an SDK connection.
    ch._ws_runner = MagicMock(start_client=AsyncMock(side_effect=started), stop_client=AsyncMock())
    monkeypatch.setattr(ch, "_fetch_bot_open_id", lambda: None)
    try:
        await ch.start()
        builder.domain.assert_called_once_with(expected_domain)
        ws_client.assert_called_once_with(
            "cli_test", "secret", domain=expected_domain,
            event_handler=ANY,
            log_level=lark.LogLevel.INFO,
        )
        assert ch._client is builder.build.return_value
        ch._ws_runner.start_client.assert_awaited_once_with(ch.name, ws_client.return_value)
    finally:
        await ch.stop()
