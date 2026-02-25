"""Simple API key authentication for the Anthropic proxy."""

from aiohttp import web


def check_auth(request: web.Request, required_key: str) -> str | None:
    """Validate the Authorization header.

    Returns an error message string if auth fails, or None if OK.
    When *required_key* is empty, all requests are accepted.
    """
    if not required_key:
        return None

    # Accept "Authorization: Bearer <key>"
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == required_key:
        return None

    # Accept "x-api-key: <key>"
    if request.headers.get("x-api-key", "") == required_key:
        return None

    return "Invalid API key"
