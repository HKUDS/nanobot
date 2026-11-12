"""Setup validation for Linear's public callback requirements."""

from typing import Any

from pydantic import ValidationError

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.linear.config import LinearConfig
from nanobot.channels.validation import check, required_checks, status_from_checks


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("linear", values)
    try:
        config = LinearConfig.model_validate(values)
        config.validate_runtime()
    except (ValidationError, ValueError) as exc:
        checks.append(check("callbacks", "Public callbacks", "fail", str(exc)))
    else:
        checks.append(
            check(
                "callbacks",
                "Public callbacks",
                "pass",
                f"Webhook: {config.webhook_url}; OAuth callback: {config.redirect_uri}",
            )
        )
    checks.append(
        check(
            "linear_app",
            "Linear OAuth app",
            "skipped",
            "OAuth credentials and scopes are verified when you connect; "
            "webhook delivery is verified by the first event.",
        )
    )
    return status_from_checks("linear", checks, missing)


__all__ = ["validate"]
