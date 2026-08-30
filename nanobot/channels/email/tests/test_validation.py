from __future__ import annotations

import pytest

from nanobot.channels.email import validation as email_validation
from nanobot.channels.validation import validate_channel_config
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def test_validate_email_presets_are_checked_without_saving(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(email_validation, "probe_tcp", lambda *_args, **_kwargs: None)

    result = validate_channel_config(
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

    assert result["status"] == "connected"
    assert result["can_enable"] is True
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
        "nanobot.channels.validation.socket.create_connection",
        lambda *_args, **_kwargs: pytest.fail("blocked target must not be connected"),
    )

    result = validate_channel_config(
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

    warnings = [check["message"] for check in result["checks"] if check["status"] == "warn"]
    assert len(warnings) == 2
    assert all("private/internal" in message for message in warnings)


def test_validate_email_rejects_neither_password_nor_oauth_configured(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hosts/usernames alone, with no password and no OAuth credentials, must
    not be reported as enable-able — the channel would never be able to
    authenticate."""
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(email_validation, "probe_tcp", lambda *_args, **_kwargs: None)

    result = validate_channel_config(
        "email",
        {
            "channels.email.consentGranted": "true",
            "channels.email.imapHost": "imap.gmail.com",
            "channels.email.imapUsername": "bot@example.com",
            "channels.email.smtpHost": "smtp.gmail.com",
            "channels.email.smtpUsername": "bot@example.com",
        },
    )

    assert result["can_enable"] is False


def test_validate_email_oauth_credentials_alone_are_enableable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OAuth tenant/client/secret alone (no IMAP/SMTP password, not yet signed
    in) must still be saveable — signing in requires the credentials to
    already be persisted."""
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(email_validation, "probe_tcp", lambda *_args, **_kwargs: None)

    result = validate_channel_config(
        "email",
        {
            "channels.email.consentGranted": "true",
            "channels.email.imapHost": "outlook.office365.com",
            "channels.email.imapUsername": "bot@example.com",
            "channels.email.smtpHost": "smtp.office365.com",
            "channels.email.smtpUsername": "bot@example.com",
            "channels.email.oauthTenantId": "tenant-1",
            "channels.email.oauthClientId": "client-1",
            "channels.email.oauthClientSecret": "secret-1",
        },
    )

    assert result["can_enable"] is True
