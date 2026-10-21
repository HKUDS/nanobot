"""Telegram setup validation owned by the channel package."""

import re
from typing import Any, cast

import httpx

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    message_from_response,
    payload,
    required_checks,
    resolve_proxy,
    status_from_checks,
    string_value,
)
from nanobot.config.loader import resolve_env_refs

_TIMEOUT_SECONDS = 4.0


def _get_me(token: str, proxy: str | None) -> dict[str, Any]:
    if proxy and "://" not in proxy:
        proxy = f"http://{proxy}"
    client_kwargs: dict[str, Any] = {"timeout": _TIMEOUT_SECONDS}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    with httpx.Client(**client_kwargs) as client:
        response = client.get(f"https://api.telegram.org/bot{token}/getMe")
        response.raise_for_status()
        data = response.json()
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def validate(values: dict[str, Any], context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("telegram", values)
    try:
        proxy = resolve_proxy(values, context)
    except ValueError as exc:
        checks.append(check("network_proxy", "Network proxy", "fail", str(exc)))
        return status_from_checks("telegram", checks, missing)
    raw_token = string_value(values.get("token"))
    token = string_value(resolve_env_refs(raw_token))
    if raw_token and not token:
        checks.append(
            check(
                "token_env",
                "Token environment variable",
                "fail",
                "Set every environment variable referenced by the bot token.",
            )
        )
    if raw_token and not token:
        return status_from_checks("telegram", checks, missing)
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
                data = _get_me(token, proxy or None)
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
            except httpx.TransportError:
                checks.append(
                    check(
                        "proxy_connection" if proxy else "get_me",
                        "Network proxy" if proxy else "Bot identity",
                        "warn",
                        (
                            "Could not reach Telegram through the network proxy."
                            if proxy
                            else "Could not reach Telegram now. Try again later."
                        ),
                    )
                )
            except Exception:
                checks.append(
                    check(
                        "get_me",
                        "Bot identity",
                        "warn",
                        "Could not verify Telegram now. Try again later.",
                    )
                )
    return status_from_checks("telegram", checks, missing)


__all__ = ["validate"]
