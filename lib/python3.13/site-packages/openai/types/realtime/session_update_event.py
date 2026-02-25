# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal, TypeAlias

from ..._models import BaseModel
from .realtime_session_create_request import RealtimeSessionCreateRequest
from .realtime_transcription_session_create_request import RealtimeTranscriptionSessionCreateRequest

__all__ = ["SessionUpdateEvent", "Session"]

Session: TypeAlias = Union[RealtimeSessionCreateRequest, RealtimeTranscriptionSessionCreateRequest]


class SessionUpdateEvent(BaseModel):
    """
    Send this event to update the session’s configuration.
    The client may send this event at any time to update any field
    except for `voice` and `model`. `voice` can be updated only if there have been no other audio outputs yet.

    When the server receives a `session.update`, it will respond
    with a `session.updated` event showing the full, effective configuration.
    Only the fields that are present in the `session.update` are updated. To clear a field like
    `instructions`, pass an empty string. To clear a field like `tools`, pass an empty array.
    To clear a field like `turn_detection`, pass `null`.
    """

    session: Session
    """Update the Realtime session.

    Choose either a realtime session or a transcription session.
    """

    type: Literal["session.update"]
    """The event type, must be `session.update`."""

    event_id: Optional[str] = None
    """Optional client-generated ID used to identify this event.

    This is an arbitrary string that a client may assign. It will be passed back if
    there is an error with the event, but the corresponding `session.updated` event
    will not include it.
    """
