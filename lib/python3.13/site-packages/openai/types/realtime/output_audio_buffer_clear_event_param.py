# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["OutputAudioBufferClearEventParam"]


class OutputAudioBufferClearEventParam(TypedDict, total=False):
    """**WebRTC/SIP Only:** Emit to cut off the current audio response.

    This will trigger the server to
    stop generating audio and emit a `output_audio_buffer.cleared` event. This
    event should be preceded by a `response.cancel` client event to stop the
    generation of the current response.
    [Learn more](https://platform.openai.com/docs/guides/realtime-conversations#client-and-server-events-for-audio-in-webrtc).
    """

    type: Required[Literal["output_audio_buffer.clear"]]
    """The event type, must be `output_audio_buffer.clear`."""

    event_id: str
    """The unique ID of the client event used for error handling."""
