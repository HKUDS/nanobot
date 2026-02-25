# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["InputAudioBufferCommittedEvent"]


class InputAudioBufferCommittedEvent(BaseModel):
    """
    Returned when an input audio buffer is committed, either by the client or
    automatically in server VAD mode. The `item_id` property is the ID of the user
    message item that will be created, thus a `conversation.item.created` event
    will also be sent to the client.
    """

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the user message item that will be created."""

    type: Literal["input_audio_buffer.committed"]
    """The event type, must be `input_audio_buffer.committed`."""

    previous_item_id: Optional[str] = None
    """
    The ID of the preceding item after which the new item will be inserted. Can be
    `null` if the item has no predecessor.
    """
