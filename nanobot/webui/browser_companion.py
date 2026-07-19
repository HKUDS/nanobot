"""Security policy for launching the local WebUI from a browser extension."""

from __future__ import annotations

from typing import Any

from nanobot.webui.http_utils import case_insensitive_header

STATUS_PATH = "/webui/companion/status"
OPEN_PATH = "/webui/companion/open"
SESSION_COOKIE_PREFIX = "nanobot_companion_"
SESSION_TTL_SECONDS = 12 * 60 * 60


def session_cookie_name(port: int) -> str:
    """Keep companion sessions isolated when several local WebUIs use different ports."""
    return f"{SESSION_COOKIE_PREFIX}{port}"


def is_top_level_user_navigation(headers: Any) -> bool:
    """Accept address-bar or extension-created tabs, not cross-site window.open calls."""
    mode = case_insensitive_header(headers, "Sec-Fetch-Mode").lower()
    destination = case_insensitive_header(headers, "Sec-Fetch-Dest").lower()
    site = case_insensitive_header(headers, "Sec-Fetch-Site").lower()
    return mode == "navigate" and destination == "document" and site == "none"
