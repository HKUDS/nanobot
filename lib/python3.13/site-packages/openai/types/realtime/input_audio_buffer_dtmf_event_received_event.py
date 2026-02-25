# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["InputAudioBufferDtmfEventReceivedEvent"]


class InputAudioBufferDtmfEventReceivedEvent(BaseModel):
    """**SIP Only:** Returned when an DTMF event is received.

    A DTMF event is a message that
    represents a telephone keypad press (0–9, *, #, A–D). The `event` property
    is the keypad that the user press. The `received_at` is the UTC Unix Timestamp
    that the server received the event.
    """

    event: str
    """The telephone keypad that was pressed by the user."""

    received_at: int
    """UTC Unix Timestamp when DTMF Event was received by server."""

    type: Literal["input_audio_buffer.dtmf_event_received"]
    """The event type, must be `input_audio_buffer.dtmf_event_received`."""
