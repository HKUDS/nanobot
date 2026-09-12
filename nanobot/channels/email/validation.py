"""Email setup validation owned by the channel package."""

import imaplib
import smtplib
import ssl
from contextlib import suppress
from typing import Any

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    int_value,
    probe_tcp,
    required_checks,
    status_from_checks,
    string_value,
    truthy,
)

_TIMEOUT_SECONDS = 4.0


class _MailboxSelectionError(Exception):
    pass


def _resolved_string(values: dict[str, Any], field: str) -> str:
    from nanobot.config.loader import resolve_env_refs

    return string_value(resolve_env_refs(string_value(values.get(field))))


def _bool_value(values: dict[str, Any], field: str, *, default: bool) -> bool:
    value = values.get(field)
    return default if value in (None, "") else truthy(value)


def _imap_login(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    mailbox: str,
    use_ssl: bool,
) -> None:
    client: Any = (
        imaplib.IMAP4_SSL(host, port, timeout=_TIMEOUT_SECONDS)
        if use_ssl
        else imaplib.IMAP4(host, port, timeout=_TIMEOUT_SECONDS)
    )
    try:
        client.login(username, password)
        try:
            status, _ = client.select(mailbox, readonly=True)
        except imaplib.IMAP4.error as exc:
            raise _MailboxSelectionError from exc
        if status != "OK":
            raise _MailboxSelectionError
    finally:
        with suppress(Exception):
            client.logout()


def _smtp_login(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    use_ssl: bool,
    use_tls: bool,
) -> None:
    client = (
        smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT_SECONDS)
        if use_ssl
        else smtplib.SMTP(host, port, timeout=_TIMEOUT_SECONDS)
    )
    with client:
        if use_tls and not use_ssl:
            client.starttls(context=ssl.create_default_context())
        client.login(username, password)


def _connection_error_message(prefix: str, exc: Exception) -> tuple[str, str]:
    if isinstance(exc, _MailboxSelectionError):
        return "fail", "IMAP connected, but the selected mailbox could not be opened."
    if isinstance(exc, (imaplib.IMAP4.error, smtplib.SMTPAuthenticationError)):
        return "fail", f"{prefix} rejected the username or password."
    if isinstance(exc, (ssl.SSLError, smtplib.SMTPNotSupportedError)):
        return "fail", f"{prefix} security settings are not accepted by the server."
    if isinstance(exc, smtplib.SMTPResponseException):
        return "fail", f"{prefix} rejected the connection settings."
    if isinstance(exc, (TimeoutError, OSError)):
        return "warn", f"Could not reach {prefix} now. Try again later."
    return "warn", f"Could not verify {prefix} now. Try again later."


def validate(
    values: dict[str, Any],
    context: ChannelValidationContext,
) -> dict[str, Any]:
    checks, missing = required_checks("email", values)
    if truthy(values.get("consentGranted")):
        checks.append(check("consent", "Mailbox consent", "pass", "Consent is enabled for this mailbox."))
    else:
        checks.append(
            check(
                "consent",
                "Mailbox consent",
                "fail",
                "Grant consent before nanobot reads this mailbox.",
            )
        )

    for prefix, default_port in (("imap", 993), ("smtp", 587)):
        label = prefix.upper()
        host = _resolved_string(values, f"{prefix}Host")
        username = _resolved_string(values, f"{prefix}Username")
        password = _resolved_string(values, f"{prefix}Password")
        unresolved = any(
            string_value(values.get(field)) and not _resolved_string(values, field)
            for field in (f"{prefix}Host", f"{prefix}Username", f"{prefix}Password")
        )
        if unresolved:
            checks.append(
                check(
                    f"{prefix}_environment",
                    f"{label} account",
                    "fail",
                    f"Set every environment variable referenced by the {label} settings.",
                )
            )
            continue
        raw_port = values.get(f"{prefix}Port")
        port = default_port if raw_port in (None, "") else int_value(raw_port)
        if not host:
            continue
        if port is None or port <= 0 or port > 65535:
            checks.append(
                check(
                    f"{prefix}_port",
                    f"{label} port",
                    "fail",
                    "Port must be between 1 and 65535.",
                )
            )
            continue
        checks.append(
            check(
                f"{prefix}_settings",
                f"{label} settings",
                "pass",
                f"{host}:{port} is set.",
            )
        )
        try:
            probe_tcp(
                host,
                port,
                allow_loopback=context.allow_local_service_access,
            )
            checks.append(
                check(
                    f"{prefix}_reachability",
                    f"{label} reachability",
                    "pass",
                    "The server accepted a TCP connection.",
                )
            )
        except Exception as exc:
            checks.append(
                check(
                    f"{prefix}_reachability",
                    f"{label} reachability",
                    "warn",
                    f"Could not verify network reachability now: {exc}",
                )
            )
            continue

        if not username or not password:
            continue
        try:
            if prefix == "imap":
                _imap_login(
                    host,
                    port,
                    username,
                    password,
                    mailbox=_resolved_string(values, "imapMailbox") or "INBOX",
                    use_ssl=_bool_value(values, "imapUseSsl", default=True),
                )
            else:
                _smtp_login(
                    host,
                    port,
                    username,
                    password,
                    use_ssl=_bool_value(values, "smtpUseSsl", default=False),
                    use_tls=_bool_value(values, "smtpUseTls", default=True),
                )
            checks.append(
                check(
                    f"{prefix}_account",
                    f"{label} account",
                    "pass",
                    f"{label} accepted the account credentials.",
                )
            )
        except Exception as exc:
            status, message = _connection_error_message(label, exc)
            checks.append(check(f"{prefix}_account", f"{label} account", status, message))

    identity = {
        "account": (
            _resolved_string(values, "fromAddress")
            or _resolved_string(values, "imapUsername")
            or _resolved_string(values, "smtpUsername")
        )
    }
    return status_from_checks("email", checks, missing, identity=identity)


__all__ = ["validate"]
