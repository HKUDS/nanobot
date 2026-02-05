# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["ResponseInputAudioParam", "InputAudio"]


class InputAudio(TypedDict, total=False):
    data: Required[str]
    """Base64-encoded audio data."""

    format: Required[Literal["mp3", "wav"]]
    """The format of the audio data. Currently supported formats are `mp3` and `wav`."""


class ResponseInputAudioParam(TypedDict, total=False):
    """An audio input to the model."""

    input_audio: Required[InputAudio]

    type: Required[Literal["input_audio"]]
    """The type of the input item. Always `input_audio`."""
