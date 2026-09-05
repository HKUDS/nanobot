"""Explicit audience policy for operation notifications."""

from typing import Literal

from nanobot.events import AgentEvent, ContextCompactionEvent, RecoveryStateEvent, RetryWaitEvent

NotificationAudience = Literal["channel", "lifecycle", "interactive"]

NOTIFICATION_AUDIENCES: dict[type[AgentEvent], NotificationAudience] = {
    ContextCompactionEvent: "channel",
    RetryWaitEvent: "lifecycle",
    RecoveryStateEvent: "interactive",
}


def notification_is_deliverable(
    event: AgentEvent, *, channel: str, publish_lifecycle: bool,
) -> bool:
    """Unknown internal events are observable but never become chat messages."""
    audience = NOTIFICATION_AUDIENCES.get(type(event))
    if audience is None:
        return False
    if audience == "lifecycle":
        return publish_lifecycle
    if audience == "interactive":
        return channel == "websocket"
    return True
