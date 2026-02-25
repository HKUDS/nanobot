# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import List
from typing_extensions import Literal, Required, TypedDict

from .realtime_transcription_session_audio_param import RealtimeTranscriptionSessionAudioParam

__all__ = ["RealtimeTranscriptionSessionCreateRequestParam"]


class RealtimeTranscriptionSessionCreateRequestParam(TypedDict, total=False):
    """Realtime transcription session object configuration."""

    type: Required[Literal["transcription"]]
    """The type of session to create.

    Always `transcription` for transcription sessions.
    """

    audio: RealtimeTranscriptionSessionAudioParam
    """Configuration for input and output audio."""

    include: List[Literal["item.input_audio_transcription.logprobs"]]
    """Additional fields to include in server outputs.

    `item.input_audio_transcription.logprobs`: Include logprobs for input audio
    transcription.
    """
