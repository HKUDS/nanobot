# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ConversationItemTruncateEvent"]


class ConversationItemTruncateEvent(BaseModel):
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

    audio_end_ms: int
    """Inclusive duration up to which audio is truncated, in milliseconds.

    If the audio_end_ms is greater than the actual audio duration, the server will
    respond with an error.
    """

    content_index: int
    """The index of the content part to truncate. Set this to `0`."""

    item_id: str
    """The ID of the assistant message item to truncate.

    Only assistant message items can be truncated.
    """

    type: Literal["conversation.item.truncate"]
    """The event type, must be `conversation.item.truncate`."""

    event_id: Optional[str] = None
    """Optional client-generated ID used to identify this event."""
