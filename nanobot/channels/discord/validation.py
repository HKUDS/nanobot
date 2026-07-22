"""Discord setup validation owned by the channel package."""

from typing import Any

import httpx

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    http_get,
    payload,
    required_checks,
    status_from_checks,
    string_value,
)


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("discord", values)
    token = string_value(values.get("token"))
    if token:
        try:
            data = http_get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token}"},
            )
            bot_id = str(data.get("id") or "")
            checks.append(check("bot_token", "Bot token", "pass", "Discord accepted the bot token."))
            identity = {
                "name": data.get("global_name") or data.get("username"),
                "account": bot_id,
            }
            if bot_id:
                checks.append(
                    check(
                        "invite",
                        "Server invite",
                        "pass",
                        "Use this generated OAuth URL to invite the bot.",
                        action_url=(
                            "https://discord.com/oauth2/authorize"
                            f"?client_id={bot_id}&scope=bot%20applications.commands"
                        ),
                    )
                )
            return payload(
                "discord",
                "connected",
                checks,
                identity=identity,
                missing_fields=missing,
            )
        except httpx.HTTPStatusError as exc:
            checks.append(
                check(
                    "bot_token",
                    "Bot token",
                    "fail",
                    f"Discord rejected the token: HTTP {exc.response.status_code}",
                )
            )
        except Exception as exc:
            checks.append(
                check("bot_token", "Bot token", "warn", f"Could not reach Discord now: {exc}")
            )
    return status_from_checks("discord", checks, missing)


__all__ = ["validate"]
