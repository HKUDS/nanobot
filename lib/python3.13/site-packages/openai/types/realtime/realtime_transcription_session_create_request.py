# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .realtime_transcription_session_audio import RealtimeTranscriptionSessionAudio

__all__ = ["RealtimeTranscriptionSessionCreateRequest"]


class RealtimeTranscriptionSessionCreateRequest(BaseModel):
    """Realtime transcription session object configuration."""

    type: Literal["transcription"]
    """The type of session to create.

    Always `transcription` for transcription sessions.
    """

    audio: Optional[RealtimeTranscriptionSessionAudio] = None
    """Configuration for input and output audio."""

    include: Optional[List[Literal["item.input_audio_transcription.logprobs"]]] = None
    """Additional fields to include in server outputs.

    `item.input_audio_transcription.logprobs`: Include logprobs for input audio
    transcription.
    """
