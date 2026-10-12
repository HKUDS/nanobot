"""Channel-owned address metadata retained for later session notifications."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from nanobot.bus.events import InboundMessage

if TYPE_CHECKING:
    from nanobot.agent.turn_delivery import TurnRoute


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


def channel_turn_route(msg: InboundMessage, session_key: str, route: "TurnRoute") -> "TurnRoute":
    """Retain adapter-owned thread addresses without persisting turn or sender data."""
    metadata = deepcopy(route.metadata)
    if (
        msg.channel == "system"
        and route.channel == "slack"
        and session_key.startswith("slack:")
        and session_key.count(":") >= 2
    ):
        metadata["slack"] = {"thread_ts": session_key.split(":", 2)[2]}
    return replace(
        route,
        metadata=metadata,
        notification_metadata=notification_metadata(route.channel, metadata),
    )
