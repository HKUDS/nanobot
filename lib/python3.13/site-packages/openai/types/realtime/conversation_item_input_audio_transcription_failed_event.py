# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ConversationItemInputAudioTranscriptionFailedEvent", "Error"]


class Error(BaseModel):
    """Details of the transcription error."""

    code: Optional[str] = None
    """Error code, if any."""

    message: Optional[str] = None
    """A human-readable error message."""

    param: Optional[str] = None
    """Parameter related to the error, if any."""

    type: Optional[str] = None
    """The type of error."""


class ConversationItemInputAudioTranscriptionFailedEvent(BaseModel):
    """
    Returned when input audio transcription is configured, and a transcription
    request for a user message failed. These events are separate from other
    `error` events so that the client can identify the related Item.
    """

    content_index: int
    """The index of the content part containing the audio."""

    error: Error
    """Details of the transcription error."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the user message item."""

    type: Literal["conversation.item.input_audio_transcription.failed"]
    """The event type, must be `conversation.item.input_audio_transcription.failed`."""
