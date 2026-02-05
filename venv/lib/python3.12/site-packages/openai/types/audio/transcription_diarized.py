# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .transcription_diarized_segment import TranscriptionDiarizedSegment

__all__ = ["TranscriptionDiarized", "Usage", "UsageTokens", "UsageTokensInputTokenDetails", "UsageDuration"]


class UsageTokensInputTokenDetails(BaseModel):
    """Details about the input tokens billed for this request."""

    audio_tokens: Optional[int] = None
    """Number of audio tokens billed for this request."""

    text_tokens: Optional[int] = None
    """Number of text tokens billed for this request."""


class UsageTokens(BaseModel):
    """Usage statistics for models billed by token usage."""

    input_tokens: int
    """Number of input tokens billed for this request."""

    output_tokens: int
    """Number of output tokens generated."""

    total_tokens: int
    """Total number of tokens used (input + output)."""

    type: Literal["tokens"]
    """The type of the usage object. Always `tokens` for this variant."""

    input_token_details: Optional[UsageTokensInputTokenDetails] = None
    """Details about the input tokens billed for this request."""


class UsageDuration(BaseModel):
    """Usage statistics for models billed by audio input duration."""

    seconds: float
    """Duration of the input audio in seconds."""

    type: Literal["duration"]
    """The type of the usage object. Always `duration` for this variant."""


Usage: TypeAlias = Annotated[Union[UsageTokens, UsageDuration], PropertyInfo(discriminator="type")]


class TranscriptionDiarized(BaseModel):
    """
    Represents a diarized transcription response returned by the model, including the combined transcript and speaker-segment annotations.
    """

    duration: float
    """Duration of the input audio in seconds."""

    segments: List[TranscriptionDiarizedSegment]
    """Segments of the transcript annotated with timestamps and speaker labels."""

    task: Literal["transcribe"]
    """The type of task that was run. Always `transcribe`."""

    text: str
    """The concatenated transcript text for the entire audio input."""

    usage: Optional[Usage] = None
    """Token or duration usage statistics for the request."""
