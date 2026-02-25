# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["AudioTranscription"]


class AudioTranscription(BaseModel):
    language: Optional[str] = None
    """The language of the input audio.

    Supplying the input language in
    [ISO-639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g. `en`)
    format will improve accuracy and latency.
    """

    model: Union[
        str,
        Literal[
            "whisper-1",
            "gpt-4o-mini-transcribe",
            "gpt-4o-mini-transcribe-2025-12-15",
            "gpt-4o-transcribe",
            "gpt-4o-transcribe-diarize",
        ],
        None,
    ] = None
    """The model to use for transcription.

    Current options are `whisper-1`, `gpt-4o-mini-transcribe`,
    `gpt-4o-mini-transcribe-2025-12-15`, `gpt-4o-transcribe`, and
    `gpt-4o-transcribe-diarize`. Use `gpt-4o-transcribe-diarize` when you need
    diarization with speaker labels.
    """

    prompt: Optional[str] = None
    """
    An optional text to guide the model's style or continue a previous audio
    segment. For `whisper-1`, the
    [prompt is a list of keywords](https://platform.openai.com/docs/guides/speech-to-text#prompting).
    For `gpt-4o-transcribe` models (excluding `gpt-4o-transcribe-diarize`), the
    prompt is a free text string, for example "expect words related to technology".
    """
