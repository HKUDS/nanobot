"""HTTP client for outbound calls to the coordinator service.

All requests automatically include the NANOBOT_API_KEY bearer token so
individual tools and channels don't need to manage auth headers themselves.
"""

import json
import os
from typing import Any

import httpx
from loguru import logger


def auth_headers() -> dict[str, str]:
    """Return the Authorization header dict for coordinator requests.

    Call this when constructing a long-lived httpx.AsyncClient so the token
    is baked in, or pass the result as `headers=` to individual requests.
    """
    api_key = os.environ.get("NANOBOT_API_KEY", "")
    if not api_key:
        logger.warning("NANOBOT_API_KEY is not set — coordinator requests will be sent without authentication and will be rejected with 403")
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def post(url: str, payload: dict[str, Any], timeout: float = 30) -> str:
    """POST JSON to the coordinator and return a normalised result string.

    Returns the JSON-encoded response body on success, or an "Error: ..."
    string on network/HTTP failure — matching the contract expected by all
    Google and X tool implementations.
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=auth_headers())
    except httpx.ConnectError:
        return "Error: Could not connect to coordinator. Is COORDINATOR_URL correct?"
    except httpx.TimeoutException:
        return f"Error: Request timed out after {int(timeout)} seconds."
    except httpx.HTTPError as exc:
        return f"Error: HTTP request failed: {exc}"

    try:
        data = resp.json()
    except Exception:
        return f"Error: Non-JSON response (status {resp.status_code}): {resp.text[:500]}"

    if resp.is_success and data.get("success"):
        return json.dumps(data, indent=2)

    detail = data.get("detail") or data.get("error") or json.dumps(data)
    return f"Error (HTTP {resp.status_code}): {detail}"


async def report_usage(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
    source: str = "agent_loop",
    timeout: float = 5,
) -> None:
    """Report token usage to the coordinator (fire-and-forget).

    Silently swallows all errors so token tracking never disrupts the agent.
    """
    coordinator_url = os.environ.get("COORDINATOR_URL", "")
    bot_id = os.environ.get("BOT_ID", "")
    if not coordinator_url or not bot_id:
        return
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return

    url = f"{coordinator_url}/internal/usage"
    payload = {
        "bot_id": bot_id,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "model": model,
        "source": source,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.post(url, json=payload, headers=auth_headers())
    except Exception as exc:
        logger.debug("Failed to report token usage: {}", exc)


async def fetch_scopes(timeout: float = 10) -> tuple[list[str], list[str]]:
    """Fetch the OAuth scopes granted for this bot's owner.

    Returns (google_scopes, x_scopes).  Raises on network or HTTP errors
    so the caller can decide how to handle a failure.
    """
    coordinator_url = os.environ.get("COORDINATOR_URL", "")
    bot_id = os.environ.get("BOT_ID", "")
    if not coordinator_url or not bot_id:
        return [], []

    url = f"{coordinator_url}/internal/scopes"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params={"bot_id": bot_id}, headers=auth_headers())
    resp.raise_for_status()
    data = resp.json()
    return data.get("google_scopes", []), data.get("x_scopes", [])
