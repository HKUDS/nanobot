from __future__ import annotations

import pytest

from nanobot.channels.validation import validate_channel_config
from nanobot.config.loader import save_config
from nanobot.config.schema import Config


@pytest.mark.parametrize(
    ("credentials", "expected_status", "expected_missing"),
    [
        ({}, "needs_setup", "password_or_accessToken"),
        ({"channels.matrix.accessToken": "token"}, "needs_setup", "deviceId"),
        ({"channels.matrix.password": "secret"}, "configured", None),
        (
            {
                "channels.matrix.accessToken": "token",
                "channels.matrix.deviceId": "DEVICE",
            },
            "configured",
            None,
        ),
    ],
)
def test_validate_matrix_requires_a_complete_login_method(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    credentials: dict[str, str],
    expected_status: str,
    expected_missing: str | None,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    result = validate_channel_config(
        "matrix",
        {
            "channels.matrix.homeserver": "https://matrix.example",
            "channels.matrix.userId": "@nanobot:matrix.example",
            **credentials,
        },
    )

    assert result["status"] == expected_status
    assert result["can_enable"] is (expected_status == "configured")
    if expected_missing is None:
        assert result["missing_fields"] == []
    else:
        assert expected_missing in result["missing_fields"]
