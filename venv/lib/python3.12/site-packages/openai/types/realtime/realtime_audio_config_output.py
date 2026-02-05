# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .realtime_audio_formats import RealtimeAudioFormats

__all__ = ["RealtimeAudioConfigOutput"]


class RealtimeAudioConfigOutput(BaseModel):
    format: Optional[RealtimeAudioFormats] = None
    """The format of the output audio."""

    speed: Optional[float] = None
    """
    The speed of the model's spoken response as a multiple of the original speed.
    1.0 is the default speed. 0.25 is the minimum speed. 1.5 is the maximum speed.
    This value can only be changed in between model turns, not while a response is
    in progress.

    This parameter is a post-processing adjustment to the audio after it is
    generated, it's also possible to prompt the model to speak faster or slower.
    """

    voice: Union[
        str, Literal["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar"], None
    ] = None
    """The voice the model uses to respond.

    Supported built-in voices are `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`,
    `shimmer`, `verse`, `marin`, and `cedar`. Voice cannot be changed during the
    session once the model has responded with audio at least once. We recommend
    `marin` and `cedar` for best quality.
    """
