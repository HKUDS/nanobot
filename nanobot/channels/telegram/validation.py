"""Telegram setup validation owned by the channel package."""

import re
from typing import Any

import httpx

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    http_get,
    message_from_response,
    payload,
    required_checks,
    status_from_checks,
    string_value,
)


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("telegram", values)
    token = string_value(values.get("token"))
    if token:
        if not re.match(r"^\d+:[A-Za-z0-9_-]{20,}$", token):
            checks.append(
                check(
                    "token_format",
                    "Token format",
                    "fail",
                    "Telegram tokens look like 123456:ABC...",
                )
            )
        else:
            checks.append(
                check("token_format", "Token format", "pass", "Looks like a BotFather token.")
            )
            try:
                data = http_get(f"https://api.telegram.org/bot{token}/getMe")
                if data.get("ok") and isinstance(data.get("result"), dict):
                    bot = data["result"]
                    identity = {
                        "name": bot.get("username") or bot.get("first_name"),
                        "account": str(bot.get("id") or ""),
                    }
                    checks.append(
                        check("get_me", "Bot identity", "pass", "Telegram accepted the bot token.")
                    )
                    return payload(
                        "telegram",
                        "connected",
                        checks,
                        identity=identity,
                        missing_fields=missing,
                    )
                checks.append(
                    check(
                        "get_me",
                        "Bot identity",
                        "fail",
                        message_from_response(data, "Telegram rejected the token."),
                    )
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                rejected = status_code in {400, 401, 403, 404}
                checks.append(
                    check(
                        "get_me",
                        "Bot identity",
                        "fail" if rejected else "warn",
                        (
                            f"Telegram rejected the token: HTTP {status_code}."
                            if rejected
                            else f"Telegram could not verify the token: HTTP {status_code}."
                        ),
                    )
                )
            except Exception:
                checks.append(
                    check(
                        "get_me",
                        "Bot identity",
                        "warn",
                        "Could not reach Telegram now. Try again later.",
                    )
                )
    return status_from_checks("telegram", checks, missing)


__all__ = ["validate"]
