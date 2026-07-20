"""Shared WebUI metadata keys and turn helpers."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

WEBUI_TURN_METADATA_KEY = "webui_turn_id"
WEBUI_MESSAGE_SOURCE_METADATA_KEY = "_webui_message_source"


def fresh_webui_turn_metadata(
    channel: str,
    metadata: Mapping[str, Any] | None,
    *,
    turn_seed: str,
) -> dict[str, Any]:
    """Copy WebUI delivery metadata and assign a fresh proactive turn id."""
    if channel != "websocket" or not metadata or metadata.get("webui") is not True:
        return {}
    out = dict(metadata)
    out[WEBUI_TURN_METADATA_KEY] = f"{turn_seed}:{uuid.uuid4().hex}"
    return out
