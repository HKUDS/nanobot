from __future__ import annotations

import imaplib

import pytest

from nanobot.channels.email import validation as email_validation
from nanobot.channels.email.manifest import SETUP_SPEC
from nanobot.channels.validation import validate_channel_config
from nanobot.config.loader import save_config
from nanobot.config.schema import Config


def test_email_exposes_connection_checks_to_setup_clients() -> None:
    assert SETUP_SPEC.verifies_connection is True


def test_validate_email_presets_are_checked_without_saving(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    original_config = config_path.read_bytes()
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(email_validation, "probe_tcp", lambda *_args, **_kwargs: None)
    login_calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        email_validation,
        "_imap_login",
        lambda *args, **kwargs: login_calls.append(("imap", args, kwargs)),
    )
    monkeypatch.setattr(
        email_validation,
        "_smtp_login",
        lambda *args, **kwargs: login_calls.append(("smtp", args, kwargs)),
    )

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
            "channels.email.trustedAuthservIds": ["mx.google.com"],
        },
    )

    assert result["status"] == "connected"
    assert result["can_enable"] is True
    assert [check["id"] for check in result["checks"]][-2:] == [
        "smtp_reachability",
        "smtp_account",
    ]
    assert login_calls == [
        (
            "imap",
            ("imap.gmail.com", 993, "bot@example.com", "imap-secret"),
            {"mailbox": "INBOX", "use_ssl": True},
        ),
        (
            "smtp",
            ("smtp.gmail.com", 587, "bot@example.com", "smtp-secret"),
            {"use_ssl": False, "use_tls": True},
        ),
    ]
    assert config_path.read_bytes() == original_config


def test_validate_email_rejects_invalid_account_credentials(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(email_validation, "probe_tcp", lambda *_args, **_kwargs: None)

    def reject_imap_login(*_args, **_kwargs) -> None:
        raise imaplib.IMAP4.error("AUTH failed")

    monkeypatch.setattr(email_validation, "_imap_login", reject_imap_login)
    monkeypatch.setattr(email_validation, "_smtp_login", lambda *_args, **_kwargs: None)

    result = validate_channel_config(
        "email",
        {
            "channels.email.consentGranted": "true",
            "channels.email.imapHost": "imap.example.com",
            "channels.email.imapUsername": "bot@example.com",
            "channels.email.imapPassword": "wrong-secret",
            "channels.email.trustedAuthservIds": ["mx.example.com"],
            "channels.email.smtpHost": "smtp.example.com",
            "channels.email.smtpUsername": "bot@example.com",
            "channels.email.smtpPassword": "smtp-secret",
        },
    )

    assert result["status"] == "invalid"
    assert result["can_enable"] is False
    assert {
        check["id"]: (check["status"], check.get("message"))
        for check in result["checks"]
    }["imap_account"] == (
        "fail",
        "IMAP rejected the username or password.",
    )


def test_validate_email_requires_trusted_authserv_ids_for_authentication(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(email_validation, "probe_tcp", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(email_validation, "_imap_login", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(email_validation, "_smtp_login", lambda *_args, **_kwargs: None)

    result = validate_channel_config(
        "email",
        {
            "channels.email.consentGranted": "true",
            "channels.email.imapHost": "imap.example.com",
            "channels.email.imapUsername": "bot@example.com",
            "channels.email.imapPassword": "imap-secret",
            "channels.email.smtpHost": "smtp.example.com",
            "channels.email.smtpUsername": "bot@example.com",
            "channels.email.smtpPassword": "smtp-secret",
        },
    )

    assert result["status"] == "needs_setup"
    assert result["can_enable"] is False
    assert "trustedAuthservIds" in result["missing_fields"]


@pytest.mark.parametrize(("anchors", "verify", "expected"), [
    (" MX.Google.COM. , mx.receiver.example ", True, "connected"),
    (["mx.google.com"], True, "connected"),
    (["*"], True, "invalid"),
    ([""], True, "invalid"),
    ([7], True, "invalid"),
    ("https://mx.google.com", True, "invalid"),
    ("", True, "needs_setup"),
    ([], False, "connected"),
    (["*"], False, "invalid"),
])
def test_validate_email_authentication_matches_runtime_and_form_values(
    tmp_path, monkeypatch, anchors, verify, expected,
) -> None:
    config_path = tmp_path / "config.json"
    save_config(Config(), config_path)
    before = config_path.read_bytes()
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)
    monkeypatch.setattr(email_validation, "probe_tcp", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(email_validation, "_imap_login", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(email_validation, "_smtp_login", lambda *_args, **_kwargs: None)
    result = validate_channel_config("email", {
        "consentGranted": True,
        "imapHost": "imap.example.com", "imapUsername": "bot@example.com", "imapPassword": "secret",
        "smtpHost": "smtp.example.com", "smtpUsername": "bot@example.com", "smtpPassword": "secret",
        "verifySpf": str(verify).lower(), "verifyDkim": str(verify).lower(),
        "trustedAuthservIds": anchors,
    })
    assert result["status"] == expected
    assert result["can_enable"] is (expected == "connected")
    assert config_path.read_bytes() == before


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
            "channels.email.trustedAuthservIds": ["outlook.office365.com"],
        },
    )

    assert result["can_enable"] is True
