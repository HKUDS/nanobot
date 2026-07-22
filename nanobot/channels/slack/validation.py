"""Slack setup validation owned by the channel package."""

from typing import Any

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    http_post,
    message_from_response,
    official_action,
    payload,
    required_checks,
    status_from_checks,
    string_value,
)


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("slack", values)
    app_token = string_value(values.get("appToken"))
    bot_token = string_value(values.get("botToken"))
    if app_token:
        checks.append(
            check(
                "app_token_prefix",
                "Socket Mode app token",
                "pass" if app_token.startswith("xapp-") else "fail",
                "App-level Socket Mode tokens start with xapp-.",
                action_url=official_action("slack"),
            )
        )
    if bot_token:
        checks.append(
            check(
                "bot_token_prefix",
                "Bot token",
                "pass" if bot_token.startswith("xoxb-") else "fail",
                "Bot tokens start with xoxb- after installing the Slack app.",
                action_url=official_action("slack"),
            )
        )
        if bot_token.startswith("xoxb-"):
            try:
                data = http_post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {bot_token}"},
                )
                if data.get("ok"):
                    identity = {
                        "name": data.get("user"),
                        "workspace": data.get("team"),
                        "account": data.get("user_id"),
                    }
                    checks.append(
                        check(
                            "auth_test",
                            "Workspace identity",
                            "pass",
                            "Slack accepted the bot token.",
                        )
                    )
                    status = "connected" if app_token.startswith("xapp-") else "configured"
                    return payload(
                        "slack",
                        status,
                        checks,
                        identity=identity,
                        missing_fields=missing,
                    )
                checks.append(
                    check(
                        "auth_test",
                        "Workspace identity",
                        "fail",
                        message_from_response(data, "Slack rejected the bot token."),
                    )
                )
            except Exception as exc:
                checks.append(
                    check(
                        "auth_test",
                        "Workspace identity",
                        "warn",
                        f"Could not reach Slack now: {exc}",
                    )
                )
    return status_from_checks("slack", checks, missing)


__all__ = ["validate"]
