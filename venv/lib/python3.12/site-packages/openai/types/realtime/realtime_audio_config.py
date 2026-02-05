# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional

from ..._models import BaseModel
from .realtime_audio_config_input import RealtimeAudioConfigInput
from .realtime_audio_config_output import RealtimeAudioConfigOutput

__all__ = ["RealtimeAudioConfig"]


class RealtimeAudioConfig(BaseModel):
    """Configuration for input and output audio."""

    input: Optional[RealtimeAudioConfigInput] = None

    output: Optional[RealtimeAudioConfigOutput] = None
