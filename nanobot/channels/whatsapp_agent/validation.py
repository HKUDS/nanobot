"""WhatsApp Agent Platform setup validation owned by the channel package."""

from typing import Any, cast

import httpx

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    required_checks,
    status_from_checks,
    string_value,
)
from nanobot.channels.whatsapp_agent.protocol import API_BASE

_PROBE_TIMEOUT_SECONDS = 6.0
# A poll probe with timeout=0 returns immediately instead of holding a slot.
_PROBE_URL = f"{API_BASE}/updates?limit=1&timeout=0"


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("whatsapp_agent", values)
    token = string_value(values.get("token"))
    if not token:
        return status_from_checks("whatsapp_agent", checks, missing)

    try:
        response = httpx.get(
            _PROBE_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_PROBE_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        checks.append(
            check(
                "agent_token",
                "API token",
                "warn",
                f"Could not reach the WhatsApp Agent API now: {exc}",
            )
        )
        return status_from_checks("whatsapp_agent", checks, missing)

    code = _error_code(response)
    if response.status_code == 401 or code == 190:
        checks.append(
            check(
                "agent_token",
                "API token",
                "fail",
                "The Authorization header was rejected. Re-copy the API key from the agent's chat.",
            )
        )
    elif response.status_code == 400 and code == 100:
        checks.append(
            check(
                "agent_token",
                "API token",
                "fail",
                "WhatsApp rejected this token. Regenerate it from the agent's chat info.",
            )
        )
    elif response.status_code in {200, 204} or response.status_code == 409:
        # 409 means the token is valid but another poller is already running.
        detail = (
            "The token is accepted. A poller is already active for this agent; "
            "keep one gateway instance per agent."
            if response.status_code == 409
            else "The token is accepted by the WhatsApp Agent API."
        )
        checks.append(check("agent_token", "API token", "pass", detail))
    else:
        checks.append(
            check(
                "agent_token",
                "API token",
                "warn",
                f"WhatsApp returned HTTP {response.status_code} while checking the token.",
            )
        )
    return status_from_checks("whatsapp_agent", checks, missing)


def _error_code(response: httpx.Response) -> int:
    try:
        payload_data: object = response.json()
    except ValueError:
        return 0
    if not isinstance(payload_data, dict):
        return 0
    body = cast(dict[str, Any], payload_data)
    error = body.get("error")
    if not isinstance(error, dict):
        return 0
    raw_code = cast(dict[str, Any], error).get("code")
    try:
        return int(cast(Any, raw_code))
    except (TypeError, ValueError):
        return 0


__all__ = ["validate"]
