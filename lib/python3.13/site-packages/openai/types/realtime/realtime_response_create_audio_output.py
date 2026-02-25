# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .realtime_audio_formats import RealtimeAudioFormats

__all__ = ["RealtimeResponseCreateAudioOutput", "Output"]


class Output(BaseModel):
    format: Optional[RealtimeAudioFormats] = None
    """The format of the output audio."""

    voice: Union[
        str, Literal["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar"], None
    ] = None
    """The voice the model uses to respond.

    Supported built-in voices are `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`,
    `shimmer`, `verse`, `marin`, and `cedar`. Voice cannot be changed during the
    session once the model has responded with audio at least once.
    """


class RealtimeResponseCreateAudioOutput(BaseModel):
    """Configuration for audio input and output."""

    output: Optional[Output] = None
