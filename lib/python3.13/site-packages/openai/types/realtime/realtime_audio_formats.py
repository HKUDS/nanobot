# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel

__all__ = ["RealtimeAudioFormats", "AudioPCM", "AudioPCMU", "AudioPCMA"]


class AudioPCM(BaseModel):
    """The PCM audio format. Only a 24kHz sample rate is supported."""

    rate: Optional[Literal[24000]] = None
    """The sample rate of the audio. Always `24000`."""

    type: Optional[Literal["audio/pcm"]] = None
    """The audio format. Always `audio/pcm`."""


class AudioPCMU(BaseModel):
    """The G.711 μ-law format."""

    type: Optional[Literal["audio/pcmu"]] = None
    """The audio format. Always `audio/pcmu`."""


class AudioPCMA(BaseModel):
    """The G.711 A-law format."""

    type: Optional[Literal["audio/pcma"]] = None
    """The audio format. Always `audio/pcma`."""


RealtimeAudioFormats: TypeAlias = Annotated[Union[AudioPCM, AudioPCMU, AudioPCMA], PropertyInfo(discriminator="type")]
