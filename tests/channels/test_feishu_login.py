import json

import httpx
import pytest

from blackcat.channels import feishu as feishu_module
from blackcat.channels.feishu import FeishuChannel
from blackcat.config import loader
from blackcat.config.schema import Config


@pytest.mark.asyncio
async def test_feishu_login_writes_credentials_to_active_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config = Config()
    config.channels.feishu = {"enabled": False, "domain": "feishu"}
    loader.save_config(config, config_path)
    monkeypatch.setattr(loader, "_current_config_path", config_path)
    monkeypatch.setattr(
        feishu_module,
        "qr_register",
        lambda initial_domain="feishu": {
            "app_id": "cli_app",
            "app_secret": "secret",
            "domain": "lark",
        },
    )

    channel = FeishuChannel({"enabled": False, "domain": "feishu"}, None)

    assert await channel.login() is True
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["channels"]["feishu"]["appId"] == "cli_app"
    assert data["channels"]["feishu"]["appSecret"] == "secret"
    assert data["channels"]["feishu"]["domain"] == "lark"
    assert data["channels"]["feishu"]["enabled"] is True


def test_begin_registration_requires_login_url(monkeypatch):
    monkeypatch.setattr(
        feishu_module,
        "_post_registration",
        lambda _base_url, _body: {"device_code": "device"},
    )

    with pytest.raises(RuntimeError, match="login URL"):
        feishu_module._begin_registration()


def test_begin_registration_preserves_login_url(monkeypatch):
    login_url = "https://accounts.feishu.cn/login?device_code=device"
    monkeypatch.setattr(
        feishu_module,
        "_post_registration",
        lambda _base_url, _body: {
            "device_code": "device",
            "verification_uri_complete": login_url,
        },
    )

    assert feishu_module._begin_registration()["qr_url"] == login_url


def test_qr_register_returns_none_on_network_error(monkeypatch):
    def raise_connect_error(_base_url, _body):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(feishu_module, "_post_registration", raise_connect_error)

    assert feishu_module.qr_register() is None


@pytest.mark.asyncio
async def test_feishu_login_creates_missing_active_config(monkeypatch, tmp_path):
    missing_config = tmp_path / "missing.json"
    monkeypatch.setattr(loader, "_current_config_path", missing_config)
    monkeypatch.setattr(
        feishu_module,
        "qr_register",
        lambda initial_domain="feishu": {
            "app_id": "cli_app",
            "app_secret": "secret",
            "domain": "feishu",
        },
    )

    channel = FeishuChannel({}, None)

    assert await channel.login() is True
    assert missing_config.exists()
    data = json.loads(missing_config.read_text(encoding="utf-8"))
    assert data["channels"]["feishu"]["appId"] == "cli_app"
