# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import TypedDict

from .realtime_audio_config_input_param import RealtimeAudioConfigInputParam
from .realtime_audio_config_output_param import RealtimeAudioConfigOutputParam

__all__ = ["RealtimeAudioConfigParam"]


class RealtimeAudioConfigParam(TypedDict, total=False):
    """Configuration for input and output audio."""

    input: RealtimeAudioConfigInputParam

    output: RealtimeAudioConfigOutputParam
