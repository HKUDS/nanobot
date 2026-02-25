# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ConversationItemTruncatedEvent"]


class ConversationItemTruncatedEvent(BaseModel):
    """
    Returned when an earlier assistant audio message item is truncated by the
    client with a `conversation.item.truncate` event. This event is used to
    synchronize the server's understanding of the audio with the client's playback.

    This action will truncate the audio and remove the server-side text transcript
    to ensure there is no text in the context that hasn't been heard by the user.
    """

    audio_end_ms: int
    """The duration up to which the audio was truncated, in milliseconds."""

    content_index: int
    """The index of the content part that was truncated."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the assistant message item that was truncated."""

    type: Literal["conversation.item.truncated"]
    """The event type, must be `conversation.item.truncated`."""
