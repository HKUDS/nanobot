"""Feishu/Lark setup validation owned by the channel package."""

from typing import Any

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import check, payload, required_checks, string_value


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("feishu", values)
    display_name = string_value(values.get("displayName") or values.get("name"))
    avatar_url = string_value(values.get("avatarUrl"))
    app_id = string_value(values.get("appId"))
    if app_id.startswith(("cli_", "oapi_")):
        checks.append(check("app_id", "App ID", "pass", "A Feishu/Lark App ID is saved."))
    elif app_id:
        checks.append(
            check(
                "app_id",
                "App ID",
                "warn",
                "App ID is saved, but it does not look like a standard Feishu App ID.",
            )
        )
    status = "connected" if not missing else "needs_setup"
    identity = {
        "name": display_name or "Feishu assistant",
        "avatar_url": avatar_url or None,
        "account": app_id,
    }
    return payload("feishu", status, checks, identity=identity, missing_fields=missing)


__all__ = ["validate"]
