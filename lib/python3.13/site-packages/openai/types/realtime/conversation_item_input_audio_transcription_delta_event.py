# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .log_prob_properties import LogProbProperties

__all__ = ["ConversationItemInputAudioTranscriptionDeltaEvent"]


class ConversationItemInputAudioTranscriptionDeltaEvent(BaseModel):
    """
    Returned when the text value of an input audio transcription content part is updated with incremental transcription results.
    """

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the item containing the audio that is being transcribed."""

    type: Literal["conversation.item.input_audio_transcription.delta"]
    """The event type, must be `conversation.item.input_audio_transcription.delta`."""

    content_index: Optional[int] = None
    """The index of the content part in the item's content array."""

    delta: Optional[str] = None
    """The text delta."""

    logprobs: Optional[List[LogProbProperties]] = None
    """The log probabilities of the transcription.

    These can be enabled by configurating the session with
    `"include": ["item.input_audio_transcription.logprobs"]`. Each entry in the
    array corresponds a log probability of which token would be selected for this
    chunk of transcription. This can help to identify if it was possible there were
    multiple valid options for a given chunk of transcription.
    """
