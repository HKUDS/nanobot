# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .audio_transcription import AudioTranscription
from .noise_reduction_type import NoiseReductionType
from .realtime_audio_formats import RealtimeAudioFormats
from .realtime_transcription_session_turn_detection import RealtimeTranscriptionSessionTurnDetection

__all__ = ["RealtimeTranscriptionSessionCreateResponse", "Audio", "AudioInput", "AudioInputNoiseReduction"]


class AudioInputNoiseReduction(BaseModel):
    """Configuration for input audio noise reduction."""

    type: Optional[NoiseReductionType] = None
    """Type of noise reduction.

    `near_field` is for close-talking microphones such as headphones, `far_field` is
    for far-field microphones such as laptop or conference room microphones.
    """


class AudioInput(BaseModel):
    format: Optional[RealtimeAudioFormats] = None
    """The PCM audio format. Only a 24kHz sample rate is supported."""

    noise_reduction: Optional[AudioInputNoiseReduction] = None
    """Configuration for input audio noise reduction."""

    transcription: Optional[AudioTranscription] = None
    """Configuration of the transcription model."""

    turn_detection: Optional[RealtimeTranscriptionSessionTurnDetection] = None
    """Configuration for turn detection.

    Can be set to `null` to turn off. Server VAD means that the model will detect
    the start and end of speech based on audio volume and respond at the end of user
    speech.
    """


class Audio(BaseModel):
    """Configuration for input audio for the session."""

    input: Optional[AudioInput] = None


class RealtimeTranscriptionSessionCreateResponse(BaseModel):
    """A Realtime transcription session configuration object."""

    id: str
    """Unique identifier for the session that looks like `sess_1234567890abcdef`."""

    object: str
    """The object type. Always `realtime.transcription_session`."""

    type: Literal["transcription"]
    """The type of session. Always `transcription` for transcription sessions."""

    audio: Optional[Audio] = None
    """Configuration for input audio for the session."""

    expires_at: Optional[int] = None
    """Expiration timestamp for the session, in seconds since epoch."""

    include: Optional[List[Literal["item.input_audio_transcription.logprobs"]]] = None
    """Additional fields to include in server outputs.

    - `item.input_audio_transcription.logprobs`: Include logprobs for input audio
      transcription.
    """
