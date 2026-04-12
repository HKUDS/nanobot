"""Tests for Feishu/Lark domain configuration."""
from unittest.mock import MagicMock

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.feishu import FeishuChannel, FeishuConfig


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
