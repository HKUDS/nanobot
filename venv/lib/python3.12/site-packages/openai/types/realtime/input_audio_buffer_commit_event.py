# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["InputAudioBufferCommitEvent"]


class InputAudioBufferCommitEvent(BaseModel):
    """
    Send this event to commit the user input audio buffer, which will create a  new user message item in the conversation. This event will produce an error  if the input audio buffer is empty. When in Server VAD mode, the client does  not need to send this event, the server will commit the audio buffer  automatically.

    Committing the input audio buffer will trigger input audio transcription  (if enabled in session configuration), but it will not create a response  from the model. The server will respond with an `input_audio_buffer.committed` event.
    """

    type: Literal["input_audio_buffer.commit"]
    """The event type, must be `input_audio_buffer.commit`."""

    event_id: Optional[str] = None
    """Optional client-generated ID used to identify this event."""
