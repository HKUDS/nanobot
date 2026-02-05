# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union, Optional
from typing_extensions import Literal, TypeAlias

from ..._models import BaseModel
from .log_prob_properties import LogProbProperties

__all__ = [
    "ConversationItemInputAudioTranscriptionCompletedEvent",
    "Usage",
    "UsageTranscriptTextUsageTokens",
    "UsageTranscriptTextUsageTokensInputTokenDetails",
    "UsageTranscriptTextUsageDuration",
]


class UsageTranscriptTextUsageTokensInputTokenDetails(BaseModel):
    """Details about the input tokens billed for this request."""

    audio_tokens: Optional[int] = None
    """Number of audio tokens billed for this request."""

    text_tokens: Optional[int] = None
    """Number of text tokens billed for this request."""


class UsageTranscriptTextUsageTokens(BaseModel):
    """Usage statistics for models billed by token usage."""

    input_tokens: int
    """Number of input tokens billed for this request."""

    output_tokens: int
    """Number of output tokens generated."""

    total_tokens: int
    """Total number of tokens used (input + output)."""

    type: Literal["tokens"]
    """The type of the usage object. Always `tokens` for this variant."""

    input_token_details: Optional[UsageTranscriptTextUsageTokensInputTokenDetails] = None
    """Details about the input tokens billed for this request."""


class UsageTranscriptTextUsageDuration(BaseModel):
    """Usage statistics for models billed by audio input duration."""

    seconds: float
    """Duration of the input audio in seconds."""

    type: Literal["duration"]
    """The type of the usage object. Always `duration` for this variant."""


Usage: TypeAlias = Union[UsageTranscriptTextUsageTokens, UsageTranscriptTextUsageDuration]


class ConversationItemInputAudioTranscriptionCompletedEvent(BaseModel):
    """
    This event is the output of audio transcription for user audio written to the
    user audio buffer. Transcription begins when the input audio buffer is
    committed by the client or server (when VAD is enabled). Transcription runs
    asynchronously with Response creation, so this event may come before or after
    the Response events.

    Realtime API models accept audio natively, and thus input transcription is a
    separate process run on a separate ASR (Automatic Speech Recognition) model.
    The transcript may diverge somewhat from the model's interpretation, and
    should be treated as a rough guide.
    """

    content_index: int
    """The index of the content part containing the audio."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the item containing the audio that is being transcribed."""

    transcript: str
    """The transcribed text."""

    type: Literal["conversation.item.input_audio_transcription.completed"]
    """
    The event type, must be `conversation.item.input_audio_transcription.completed`.
    """

    usage: Usage
    """
    Usage statistics for the transcription, this is billed according to the ASR
    model's pricing rather than the realtime model's pricing.
    """

    logprobs: Optional[List[LogProbProperties]] = None
    """The log probabilities of the transcription."""
