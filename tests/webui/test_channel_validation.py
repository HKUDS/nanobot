from __future__ import annotations

import httpx
import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.webui import channel_validation
from nanobot.webui.channel_validation import validate_channel_config


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
    monkeypatch.setattr(channel_validation, "_http_post", lambda *_args, **_kwargs: {"ok": True})

    payload = validate_channel_config(
        "slack",
        {
            "channels.slack.appToken": "",
            "channels.slack.botToken": "",
        },
    )

    assert payload["status"] == "connected"
    saved = load_config(config_path)
    assert saved.channels.slack["appToken"] == "xapp-old"
    assert saved.channels.slack["botToken"] == "xoxb-old"


def test_validate_telegram_bad_token_is_invalid(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    payload = validate_channel_config("telegram", {"channels.telegram.token": "not-a-token"})

    assert payload["status"] == "invalid"
    assert payload["can_enable"] is False
    assert payload["missing_fields"] == []


def test_validate_telegram_does_not_expose_saved_token_in_http_errors(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:abcdefghijklmnopqrstuvwxyz"
    config_path = tmp_path / "config.json"
    save_config(
        Config.model_validate({"channels": {"telegram": {"token": token}}}),
        config_path,
    )
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def raise_http_error(url: str, **_kwargs) -> dict:
        request = httpx.Request("GET", url)
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr(channel_validation, "_http_get", raise_http_error)

    payload = validate_channel_config("telegram", {"channels.telegram.token": ""})

    assert token not in str(payload)
    assert any("HTTP 401" in check.get("message", "") for check in payload["checks"])


def test_validate_email_presets_are_checked_without_saving(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(channel_validation, "_probe_tcp", lambda *_args, **_kwargs: None)

    payload = validate_channel_config(
        "email",
        {
            "channels.email.consentGranted": "true",
            "channels.email.imapHost": "imap.gmail.com",
            "channels.email.imapUsername": "bot@example.com",
            "channels.email.imapPassword": "imap-secret",
            "channels.email.smtpHost": "smtp.gmail.com",
            "channels.email.smtpUsername": "bot@example.com",
            "channels.email.smtpPassword": "smtp-secret",
        },
    )

    assert payload["status"] == "connected"
    assert payload["can_enable"] is True
    assert not hasattr(load_config(config_path).channels, "email")


def test_validate_email_blocks_private_targets_when_local_access_is_disabled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.tools.webui_allow_local_service_access = False
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(
        channel_validation.socket,
        "create_connection",
        lambda *_args, **_kwargs: pytest.fail("blocked target must not be connected"),
    )

    payload = validate_channel_config(
        "email",
        {
            "channels.email.consentGranted": "true",
            "channels.email.imapHost": "127.0.0.1",
            "channels.email.imapUsername": "bot@example.com",
            "channels.email.imapPassword": "imap-secret",
            "channels.email.smtpHost": "192.168.1.10",
            "channels.email.smtpUsername": "bot@example.com",
            "channels.email.smtpPassword": "smtp-secret",
        },
    )

    warnings = [check["message"] for check in payload["checks"] if check["status"] == "warn"]
    assert len(warnings) == 2
    assert all("private/internal" in message for message in warnings)


def test_probe_tcp_connects_to_the_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    connected: list[tuple[str, int]] = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        channel_validation,
        "resolve_url_target",
        lambda *_args, **_kwargs: (True, "", ("203.0.113.10",)),
    )
    monkeypatch.setattr(
        channel_validation.socket,
        "create_connection",
        lambda target, **_kwargs: connected.append(target) or FakeSocket(),
    )

    channel_validation._probe_tcp("mail.example.com", 2525)

    assert connected == [("203.0.113.10", 2525)]


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

    payload = validate_channel_config("dingtalk", {})

    assert payload["status"] == "configured"
    assert payload["can_enable"] is True
    assert any(check["status"] == "skipped" for check in payload["checks"])


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

    payload = validate_channel_config(
        "matrix",
        {
            "channels.matrix.homeserver": "https://matrix.example",
            "channels.matrix.userId": "@nanobot:matrix.example",
            **credentials,
        },
    )

    assert payload["status"] == expected_status
    assert payload["can_enable"] is (expected_status == "configured")
    if expected_missing is None:
        assert payload["missing_fields"] == []
    else:
        assert expected_missing in payload["missing_fields"]
