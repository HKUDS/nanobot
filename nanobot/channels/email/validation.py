"""Email setup validation owned by the channel package."""

from typing import Any

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.email import ms_oauth as email_oauth
from nanobot.channels.validation import (
    check,
    int_value,
    probe_tcp,
    required_checks,
    status_from_checks,
    string_value,
    truthy,
)


def validate(
    values: dict[str, Any],
    context: ChannelValidationContext,
) -> dict[str, Any]:
    checks, missing = required_checks("email", values)
    if truthy(values.get("consentGranted")):
        checks.append(
            check("consent", "Mailbox consent", "pass", "Consent is enabled for this mailbox.")
        )
    else:
        checks.append(
            check(
                "consent",
                "Mailbox consent",
                "fail",
                "Grant consent before nanobot reads this mailbox.",
            )
        )

    imap_password = string_value(values.get("imapPassword"))
    smtp_password = string_value(values.get("smtpPassword"))
    oauth_tenant_id = string_value(values.get("oauthTenantId"))
    oauth_client_id = string_value(values.get("oauthClientId"))
    oauth_client_secret = string_value(values.get("oauthClientSecret"))
    use_oauth = bool(oauth_tenant_id and oauth_client_id and oauth_client_secret)
    use_password = bool(imap_password and smtp_password)

    if use_password:
        checks.append(
            check("auth_method", "Authentication", "pass", "IMAP/SMTP password is configured.")
        )
    elif use_oauth:
        checks.append(
            check("auth_method", "Authentication", "pass", "Microsoft OAuth is configured.")
        )
    else:
        missing.append("imapPassword_smtpPassword_or_oauth")
        checks.append(
            check(
                "auth_method",
                "Authentication",
                "fail",
                "Add an IMAP/SMTP password, or a Microsoft tenant ID/client ID/client secret.",
            )
        )

    if use_oauth:
        mailbox = string_value(
            values.get("fromAddress") or values.get("imapUsername") or values.get("smtpUsername")
        )
        signed_in = bool(
            mailbox
            and email_oauth.get_email_oauth_login_status(oauth_tenant_id, oauth_client_id, mailbox)
        )
        checks.append(
            check(
                "oauth_signin",
                "Microsoft sign-in",
                # "warn", not "fail": a "fail" check forces can_enable=False,
                # which stops the WebUI from ever saving these credentials —
                # but signing in requires them to already be saved first.
                "pass" if signed_in else "warn",
                "Signed in."
                if signed_in
                else "Save, then run `nanobot channels login email` to sign in with this mailbox.",
            )
        )

    for prefix, default_port in (("imap", 993), ("smtp", 587)):
        host = string_value(values.get(f"{prefix}Host"))
        port = int_value(values.get(f"{prefix}Port")) or default_port
        if not host:
            continue
        if port <= 0 or port > 65535:
            checks.append(
                check(
                    f"{prefix}_port",
                    f"{prefix.upper()} port",
                    "fail",
                    "Port must be between 1 and 65535.",
                )
            )
            continue
        checks.append(
            check(
                f"{prefix}_settings",
                f"{prefix.upper()} settings",
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
                    f"{prefix.upper()} reachability",
                    "pass",
                    "The server accepted a TCP connection.",
                )
            )
        except Exception as exc:
            checks.append(
                check(
                    f"{prefix}_reachability",
                    f"{prefix.upper()} reachability",
                    "warn",
                    f"Could not verify network reachability now: {exc}",
                )
            )

    identity = {
        "account": string_value(
            values.get("fromAddress") or values.get("imapUsername") or values.get("smtpUsername")
        )
    }
    return status_from_checks("email", checks, missing, identity=identity)


__all__ = ["validate"]
