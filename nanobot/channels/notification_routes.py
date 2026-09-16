"""Channel-owned address metadata retained for later session notifications."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast


def notification_metadata(channel: str, source: Mapping[str, Any]) -> dict[str, Any]:
    """Keep thread addresses without retaining sender data or a completed turn owner."""
    channel_type = channel.split(".", 1)[0]
    fields = {
        "telegram": ("message_thread_id",),
        "matrix": ("thread_root_event_id", "thread_reply_to_event_id"),
        "feishu": ("message_id", "thread_id", "chat_type"),
    }.get(channel_type, ())
    metadata = {key: source[key] for key in fields if key in source}
    if channel_type in {"slack", "mattermost"}:
        nested = source.get(channel_type)
        if isinstance(nested, dict):
            nested = cast(dict[str, Any], nested)
            fields = ("thread_ts",) if channel_type == "slack" else ("root_id", "thread_ts")
            metadata[channel_type] = {key: nested[key] for key in fields if key in nested}
    return deepcopy(metadata)
