"""On-demand version checker for nanobot-ai releases.

Checks PyPI for newer versions when explicitly requested (no background polling).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version

from nanobot import __version__

logger = logging.getLogger(__name__)

_PYPI_URL = "https://pypi.org/pypi/nanobot-ai/json"
_CACHE_TTL_S = 300  # 5 minutes cache to avoid hammering PyPI

_cache: tuple[float, str | None] = (0.0, None)


def check_for_update() -> dict[str, Any] | None:
    """Check PyPI for a newer version. Returns update info dict or None if up-to-date.

    Uses a short cache to avoid repeated requests within the TTL window.
    This is a blocking call — invoke from a thread or background task.
    """
    global _cache
    now = time.monotonic()
    cached_at, cached_val = _cache
    if now - cached_at < _CACHE_TTL_S and cached_val is not None:
        latest = cached_val
    else:
        try:
            resp = httpx.get(_PYPI_URL, timeout=5.0, follow_redirects=True)
            resp.raise_for_status()
            latest = resp.json().get("info", {}).get("version")
        except Exception as exc:
            raise RuntimeError("Could not check PyPI. Check your connection and retry.") from exc

    if not isinstance(latest, str) or not latest:
        raise ValueError("PyPI returned no release version.")
    try:
        parsed = Version(latest)
        if parsed.is_prerelease or parsed.is_devrelease:
            raise ValueError("PyPI returned a prerelease instead of a stable release.")
        _cache = (now, latest)
        if Version(latest) <= Version(__version__):
            return None
    except InvalidVersion as exc:
        raise ValueError("Could not compare release versions.") from exc
    return {
        "currentVersion": __version__,
        "latestVersion": latest,
        "pypiUrl": "https://pypi.org/project/nanobot-ai/",
    }
