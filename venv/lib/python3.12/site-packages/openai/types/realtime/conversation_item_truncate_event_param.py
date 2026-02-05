# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ConversationItemTruncateEventParam"]


class ConversationItemTruncateEventParam(TypedDict, total=False):
    """Send this event to truncate a previous assistant message’s audio.

    The server
    will produce audio faster than realtime, so this event is useful when the user
    interrupts to truncate audio that has already been sent to the client but not
    yet played. This will synchronize the server's understanding of the audio with
    the client's playback.

    Truncating audio will delete the server-side text transcript to ensure there
    is not text in the context that hasn't been heard by the user.

    If successful, the server will respond with a `conversation.item.truncated`
    event.
    """

    audio_end_ms: Required[int]
    """Inclusive duration up to which audio is truncated, in milliseconds.

    If the audio_end_ms is greater than the actual audio duration, the server will
    respond with an error.
    """

    content_index: Required[int]
    """The index of the content part to truncate. Set this to `0`."""

    item_id: Required[str]
    """The ID of the assistant message item to truncate.

    Only assistant message items can be truncated.
    """

    type: Required[Literal["conversation.item.truncate"]]
    """The event type, must be `conversation.item.truncate`."""

    event_id: str
    """Optional client-generated ID used to identify this event."""
