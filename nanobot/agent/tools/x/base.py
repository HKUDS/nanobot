"""Shared helpers for X (Twitter) tools."""

import json
import os
from typing import Any

import httpx

from nanobot.agent.tools.base import Tool


class XBaseTool(Tool):
    """
    Abstract base for X tools.

    Provides the coordinator URL / bot ID resolution and the shared
    HTTP POST helper that every X tool needs.
    """

    def _env(self) -> tuple[str, str] | str:
        """Return (coordinator_url, bot_id) or an error string."""
        coordinator_url = os.environ.get("COORDINATOR_URL")
        bot_id = os.environ.get("BOT_ID")
        if not coordinator_url:
            return "Error: COORDINATOR_URL environment variable is not set."
        if not bot_id:
            return "Error: BOT_ID environment variable is not set."
        return coordinator_url, bot_id

    @staticmethod
    async def _post(url: str, payload: dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload)
        except httpx.ConnectError:
            return "Error: Could not connect to coordinator. Is COORDINATOR_URL correct?"
        except httpx.TimeoutException:
            return "Error: Request timed out after 30 seconds."
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
