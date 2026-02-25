# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .realtime_session_create_response import RealtimeSessionCreateResponse
from .realtime_transcription_session_create_response import RealtimeTranscriptionSessionCreateResponse

__all__ = ["ClientSecretCreateResponse", "Session"]

Session: TypeAlias = Annotated[
    Union[RealtimeSessionCreateResponse, RealtimeTranscriptionSessionCreateResponse], PropertyInfo(discriminator="type")
]


class ClientSecretCreateResponse(BaseModel):
    """Response from creating a session and client secret for the Realtime API."""

    expires_at: int
    """Expiration timestamp for the client secret, in seconds since epoch."""

    session: Session
    """The session configuration for either a realtime or transcription session."""

    value: str
    """The generated client secret value."""
