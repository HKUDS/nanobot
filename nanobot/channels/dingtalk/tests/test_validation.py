from __future__ import annotations

import pytest

from nanobot.channels.validation import validate_channel_config
from nanobot.config.loader import save_config
from nanobot.config.schema import Config


def test_validate_manual_channel_returns_configured(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate(
            {
                "channels": {
                    "dingtalk": {
                        "clientId": "ding-client",
                        "clientSecret": "ding-secret",
                    }
                }
            }
        ),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    result = validate_channel_config("dingtalk", {})

    assert result["status"] == "configured"
    assert result["can_enable"] is True
    assert any(check["status"] == "skipped" for check in result["checks"])
