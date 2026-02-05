# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict

from .noise_reduction_type import NoiseReductionType
from .audio_transcription_param import AudioTranscriptionParam
from .realtime_audio_formats_param import RealtimeAudioFormatsParam
from .realtime_audio_input_turn_detection_param import RealtimeAudioInputTurnDetectionParam

__all__ = ["RealtimeAudioConfigInputParam", "NoiseReduction"]


class NoiseReduction(TypedDict, total=False):
    """Configuration for input audio noise reduction.

    This can be set to `null` to turn off.
    Noise reduction filters audio added to the input audio buffer before it is sent to VAD and the model.
    Filtering the audio can improve VAD and turn detection accuracy (reducing false positives) and model performance by improving perception of the input audio.
    """

    type: NoiseReductionType
    """Type of noise reduction.

    `near_field` is for close-talking microphones such as headphones, `far_field` is
    for far-field microphones such as laptop or conference room microphones.
    """


class RealtimeAudioConfigInputParam(TypedDict, total=False):
    format: RealtimeAudioFormatsParam
    """The format of the input audio."""

    noise_reduction: NoiseReduction
    """Configuration for input audio noise reduction.

    This can be set to `null` to turn off. Noise reduction filters audio added to
    the input audio buffer before it is sent to VAD and the model. Filtering the
    audio can improve VAD and turn detection accuracy (reducing false positives) and
    model performance by improving perception of the input audio.
    """

    transcription: AudioTranscriptionParam
    """
    Configuration for input audio transcription, defaults to off and can be set to
    `null` to turn off once on. Input audio transcription is not native to the
    model, since the model consumes audio directly. Transcription runs
    asynchronously through
    [the /audio/transcriptions endpoint](https://platform.openai.com/docs/api-reference/audio/createTranscription)
    and should be treated as guidance of input audio content rather than precisely
    what the model heard. The client can optionally set the language and prompt for
    transcription, these offer additional guidance to the transcription service.
    """

    turn_detection: Optional[RealtimeAudioInputTurnDetectionParam]
    """Configuration for turn detection, ether Server VAD or Semantic VAD.

    This can be set to `null` to turn off, in which case the client must manually
    trigger model response.

    Server VAD means that the model will detect the start and end of speech based on
    audio volume and respond at the end of user speech.

    Semantic VAD is more advanced and uses a turn detection model (in conjunction
    with VAD) to semantically estimate whether the user has finished speaking, then
    dynamically sets a timeout based on this probability. For example, if user audio
    trails off with "uhhm", the model will score a low probability of turn end and
    wait longer for the user to continue speaking. This can be useful for more
    natural conversations, but may have a higher latency.
    """
