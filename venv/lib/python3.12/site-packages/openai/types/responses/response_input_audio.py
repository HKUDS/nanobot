# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseInputAudio", "InputAudio"]


class InputAudio(BaseModel):
    data: str
    """Base64-encoded audio data."""

    format: Literal["mp3", "wav"]
    """The format of the audio data. Currently supported formats are `mp3` and `wav`."""


class ResponseInputAudio(BaseModel):
    """An audio input to the model."""

    input_audio: InputAudio

    type: Literal["input_audio"]
    """The type of the input item. Always `input_audio`."""
