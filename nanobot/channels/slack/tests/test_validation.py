from __future__ import annotations

import pytest

from nanobot.channels.slack import validation as slack_validation
from nanobot.channels.validation import validate_channel_config
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def test_validate_channel_does_not_write_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    config = Config.model_validate(
        {
            "channels": {
                "slack": {
                    "appToken": "xapp-old",
                    "botToken": "xoxb-old",
                    "groupPolicy": "mention",
                }
            }
        }
    )
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(slack_validation, "http_post", lambda *_args, **_kwargs: {"ok": True})

    result = validate_channel_config(
        "slack",
        {
            "channels.slack.appToken": "",
            "channels.slack.botToken": "",
        },
    )

    assert result["status"] == "connected"
    checks = {check["id"]: check for check in result["checks"]}
    assert checks["app_token_prefix"]["action_url"] == "https://api.slack.com/apps"
    assert "action_url" not in checks["bot_token_prefix"]
    saved = load_config(config_path)
    assert saved.channels.slack["appToken"] == "xapp-old"
    assert saved.channels.slack["botToken"] == "xoxb-old"
