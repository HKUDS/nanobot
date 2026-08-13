"""Matrix setup validation owned by the channel package."""

from typing import Any

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import check, required_checks, status_from_checks, string_value


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("matrix", values)
    password = string_value(values.get("password"))
    access_token = string_value(values.get("accessToken"))
    device_id = string_value(values.get("deviceId"))

    if password:
        checks.append(check("login", "Login credentials", "pass", "Password login is configured."))
    elif access_token and device_id:
        checks.append(
            check(
                "login",
                "Login credentials",
                "pass",
                "Access token login is configured with its device ID.",
            )
        )
    else:
        if not password and not access_token:
            missing.append("password_or_accessToken")
            message = "Add a password, or an access token with its device ID."
        else:
            missing.append("deviceId")
            message = "A device ID is required with an access token."
        checks.append(check("login", "Login credentials", "fail", message))

    checks.append(
        check(
            "manual_review",
            "Matrix account",
            "skipped",
            "Room access is verified when the channel starts.",
        )
    )
    return status_from_checks("matrix", checks, list(dict.fromkeys(missing)))


__all__ = ["validate"]
