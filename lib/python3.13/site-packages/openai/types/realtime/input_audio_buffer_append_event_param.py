# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["InputAudioBufferAppendEventParam"]


class InputAudioBufferAppendEventParam(TypedDict, total=False):
    """Send this event to append audio bytes to the input audio buffer.

    The audio
    buffer is temporary storage you can write to and later commit. A "commit" will create a new
    user message item in the conversation history from the buffer content and clear the buffer.
    Input audio transcription (if enabled) will be generated when the buffer is committed.

    If VAD is enabled the audio buffer is used to detect speech and the server will decide
    when to commit. When Server VAD is disabled, you must commit the audio buffer
    manually. Input audio noise reduction operates on writes to the audio buffer.

    The client may choose how much audio to place in each event up to a maximum
    of 15 MiB, for example streaming smaller chunks from the client may allow the
    VAD to be more responsive. Unlike most other client events, the server will
    not send a confirmation response to this event.
    """

    audio: Required[str]
    """Base64-encoded audio bytes.

    This must be in the format specified by the `input_audio_format` field in the
    session configuration.
    """

    type: Required[Literal["input_audio_buffer.append"]]
    """The event type, must be `input_audio_buffer.append`."""

    event_id: str
    """Optional client-generated ID used to identify this event."""
