"""Simple API key authentication for the proxy server."""

from aiohttp import web


def check_auth(request: web.Request, required_key: str) -> str | None:
    """Validate the request against the required API key.

    Returns None if authorized, or an error message string if not.
    """
    if not required_key:
        return None  # empty key = accept all requests

    # Accept "Authorization: Bearer <key>"
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == required_key:
        return None

    # Accept "x-api-key: <key>"
    if request.headers.get("x-api-key", "") == required_key:
        return None

    return "Invalid API key"
