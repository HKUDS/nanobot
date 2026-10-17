"""Channel-aware discovery using the same verified feed as update planning."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from packaging.version import Version

import nanobot
from nanobot.installation_lock import installation_state_dir
from nanobot.release_feed import ReleaseFeed, ReleaseFeedError
from nanobot.update_channel import read_update_channel


async def _check() -> dict[str, Any]:
    selection = read_update_channel()
    current = nanobot.__version__
    status: dict[str, Any] = {
        "channel": selection.channel, "revision": selection.revision,
        "currentVersion": current, "state": "unavailable",
    }
    result: dict[str, Any] = {"updateAvailable": None, "releaseStatus": status}
    try:
        async with ReleaseFeed(installation_state_dir() / "releases") as feed:
            target, withdrawn = await feed.discover(selection.channel, current)
        if target is not None and Version(target.version) > Version(current):
            result["updateAvailable"] = {
                "currentVersion": current, "latestVersion": target.version,
                "releaseUrl": f"https://github.com/HKUDS/nanobot/releases/tag/v{target.version}",
            }
            status["state"] = "available"
        elif target is not None:
            status["state"] = (
                "waiting_stable" if selection.channel == "stable" and Version(current).is_prerelease
                else "ahead" if Version(current) > Version(target.version) else "current"
            )
        if withdrawn:
            status["state"] = "withdrawn"
    except ReleaseFeedError as exc:
        # This concerns the candidate, not necessarily the installed version.
        status["state"] = "unavailable" if exc.code == "withdrawn" else exc.code
    except (httpx.HTTPError, ValueError, OSError):
        status["state"] = "unavailable"
    if read_update_channel() != selection:
        raise ValueError("Update channel changed while checking; check again")
    return result


def check_for_update() -> dict[str, Any]:
    """Blocking settings adapter. Every check is fresh and never installs.

    The feed's ETag cache guards generations, not availability. Older clients
    still read updateAvailable; channel status is additive.
    """
    return asyncio.run(_check())
