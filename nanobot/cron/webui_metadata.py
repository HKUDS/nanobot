"""WebUI metadata helpers for cron deliveries."""

from __future__ import annotations

import uuid
from typing import Any

from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY


def cron_proactive_delivery_metadata(
    channel: str,
    metadata: dict[str, Any] | None,
    *,
    turn_seed: str,
    source_label: str | None = None,
) -> dict[str, Any]:
    """Return channel metadata for a fresh proactive cron delivery turn."""
    out = dict(metadata or {})
    out.pop(WEBUI_TURN_METADATA_KEY, None)
    if channel == "websocket":
        out[WEBUI_TURN_METADATA_KEY] = f"{turn_seed}:{uuid.uuid4().hex}"
        source: dict[str, str] = {"kind": "cron"}
        if source_label:
            source["label"] = source_label
        out[WEBUI_MESSAGE_SOURCE_METADATA_KEY] = source
    return out
