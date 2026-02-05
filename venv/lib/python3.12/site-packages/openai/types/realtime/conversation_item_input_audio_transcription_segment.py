# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ConversationItemInputAudioTranscriptionSegment"]


class ConversationItemInputAudioTranscriptionSegment(BaseModel):
    """Returned when an input audio transcription segment is identified for an item."""

    id: str
    """The segment identifier."""

    content_index: int
    """The index of the input audio content part within the item."""

    end: float
    """End time of the segment in seconds."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the item containing the input audio content."""

    speaker: str
    """The detected speaker label for this segment."""

    start: float
    """Start time of the segment in seconds."""

    text: str
    """The text for this segment."""

    type: Literal["conversation.item.input_audio_transcription.segment"]
    """The event type, must be `conversation.item.input_audio_transcription.segment`."""
