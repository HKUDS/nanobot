# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import Literal, TypedDict

__all__ = ["AudioTranscriptionParam"]


class AudioTranscriptionParam(TypedDict, total=False):
    language: str
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
    ]
    """The model to use for transcription.

    Current options are `whisper-1`, `gpt-4o-mini-transcribe`,
    `gpt-4o-mini-transcribe-2025-12-15`, `gpt-4o-transcribe`, and
    `gpt-4o-transcribe-diarize`. Use `gpt-4o-transcribe-diarize` when you need
    diarization with speaker labels.
    """

    prompt: str
    """
    An optional text to guide the model's style or continue a previous audio
    segment. For `whisper-1`, the
    [prompt is a list of keywords](https://platform.openai.com/docs/guides/speech-to-text#prompting).
    For `gpt-4o-transcribe` models (excluding `gpt-4o-transcribe-diarize`), the
    prompt is a free text string, for example "expect words related to technology".
    """
