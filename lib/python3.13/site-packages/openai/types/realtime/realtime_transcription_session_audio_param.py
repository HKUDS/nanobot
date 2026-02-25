# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import TypedDict

from .realtime_transcription_session_audio_input_param import RealtimeTranscriptionSessionAudioInputParam

__all__ = ["RealtimeTranscriptionSessionAudioParam"]


class RealtimeTranscriptionSessionAudioParam(TypedDict, total=False):
    """Configuration for input and output audio."""

    input: RealtimeTranscriptionSessionAudioInputParam
