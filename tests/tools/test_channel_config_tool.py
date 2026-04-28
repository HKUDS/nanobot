"""Tests for the channel config agent tool."""

import json

import pytest

from nanobot.agent.tools.channel_config import ConfigureChannelTool
from nanobot.config.loader import set_config_path
from nanobot.config.schema import Config


@pytest.mark.asyncio
async def test_configure_channel_updates_telegram_settings(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(Config().model_dump(by_alias=True)), encoding="utf-8")
    set_config_path(config_path)

    tool = ConfigureChannelTool()
    result = await tool.execute(
        channel="telegram",
        enabled=True,
        settings={
            "token": "123:secret",
            "allowFrom": ["42"],
            "replyToMessage": True,
        },
    )

    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))

    assert "Restart `nanobot gateway`" in result
    assert "***" in result
    assert "123:secret" not in result
    assert saved.channels.telegram["enabled"] is True
    assert saved.channels.telegram["token"] == "123:secret"
    assert saved.channels.telegram["allowFrom"] == ["42"]
    assert saved.channels.telegram["replyToMessage"] is True


@pytest.mark.asyncio
async def test_configure_channel_rejects_unknown_channel(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(Config().model_dump(by_alias=True)), encoding="utf-8")
    set_config_path(config_path)

    tool = ConfigureChannelTool()
    result = await tool.execute(channel="nope", enabled=True)

    assert result.startswith("Error: Unknown channel")


@pytest.mark.asyncio
async def test_configure_channel_updates_agenthifive_channel_settings(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(Config().model_dump(by_alias=True)), encoding="utf-8")
    set_config_path(config_path)

    tool = ConfigureChannelTool()
    result = await tool.execute(
        channel="agenthifive",
        enabled=True,
        settings={
            "providers": {
                "telegram": {
                    "enabled": True,
                    "allowFrom": ["8279370215"],
                }
            }
        },
    )

    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))

    assert "Restart `nanobot gateway`" in result
    assert saved.channels.agenthifive["enabled"] is True
    assert saved.channels.agenthifive["providers"]["telegram"]["enabled"] is True
    assert saved.channels.agenthifive["providers"]["telegram"]["allowFrom"] == ["8279370215"]


@pytest.mark.asyncio
async def test_configure_channel_updates_agenthifive_slack_settings(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(Config().model_dump(by_alias=True)), encoding="utf-8")
    set_config_path(config_path)

    tool = ConfigureChannelTool()
    result = await tool.execute(
        channel="agenthifive",
        enabled=True,
        settings={
            "providers": {
                "slack": {
                    "enabled": True,
                    "allowFrom": ["U123"],
                }
            }
        },
    )

    saved = Config.model_validate(json.loads(config_path.read_text(encoding="utf-8")))

    assert "Restart `nanobot gateway`" in result
    assert saved.channels.agenthifive["enabled"] is True
    assert saved.channels.agenthifive["providers"]["slack"]["enabled"] is True
    assert saved.channels.agenthifive["providers"]["slack"]["allowFrom"] == ["U123"]
