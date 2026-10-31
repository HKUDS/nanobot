from __future__ import annotations

from typing import Any

import httpx
from packaging.version import Version

import nanobot
from nanobot.installation_lock import installation_state_dir
from nanobot.release_feed import ReleaseFeed, ReleaseFeedError
from nanobot.update_channel import read_update_channel


async def check_for_update() -> dict[str, Any]:
    """Check fresh release data on the caller's event loop without installing.

    The feed shares the gateway's pinned-DNS transport lock. Keep discovery on
    that loop rather than creating a temporary event loop in a worker thread.
    """
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
