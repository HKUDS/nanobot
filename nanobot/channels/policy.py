"""Shared channel delivery policy helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nanobot.config.schema import ChannelsConfig


def should_deliver_message(
    channels_config: ChannelsConfig | None,
    metadata: Mapping[str, Any] | None,
) -> bool:
    """Return whether a message should be emitted for the current channel policy."""
    if channels_config is None:
        return True

    message_metadata = metadata or {}
    if not message_metadata.get("_progress"):
        return True

    if message_metadata.get("_tool_hint"):
        return channels_config.send_tool_hints

    return channels_config.send_progress
