import json

import pytest
from typer.testing import CliRunner

from nanobot.channels import feishu as feishu_module
from nanobot.channels.feishu import FeishuChannel
from nanobot.cli.commands import app
from nanobot.config import loader
from nanobot.config.schema import Config


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
            "bot_name": None,
            "bot_open_id": None,
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


def test_channels_login_feishu_requires_default_config_file(monkeypatch, tmp_path):
    missing_config = tmp_path / "missing.json"
    monkeypatch.setattr(loader, "get_config_path", lambda: missing_config)

    result = CliRunner().invoke(app, ["channels", "login", "feishu"])

    assert result.exit_code == 1
    assert "No configuration file found" in result.output
