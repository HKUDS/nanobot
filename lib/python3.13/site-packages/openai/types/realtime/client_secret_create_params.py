# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import Literal, TypeAlias, TypedDict

from .realtime_session_create_request_param import RealtimeSessionCreateRequestParam
from .realtime_transcription_session_create_request_param import RealtimeTranscriptionSessionCreateRequestParam

__all__ = ["ClientSecretCreateParams", "ExpiresAfter", "Session"]


class ClientSecretCreateParams(TypedDict, total=False):
    expires_after: ExpiresAfter
    """Configuration for the client secret expiration.

    Expiration refers to the time after which a client secret will no longer be
    valid for creating sessions. The session itself may continue after that time
    once started. A secret can be used to create multiple sessions until it expires.
    """

    session: Session
    """Session configuration to use for the client secret.

    Choose either a realtime session or a transcription session.
    """


class ExpiresAfter(TypedDict, total=False):
    """Configuration for the client secret expiration.

    Expiration refers to the time after which
    a client secret will no longer be valid for creating sessions. The session itself may
    continue after that time once started. A secret can be used to create multiple sessions
    until it expires.
    """

    anchor: Literal["created_at"]
    """
    The anchor point for the client secret expiration, meaning that `seconds` will
    be added to the `created_at` time of the client secret to produce an expiration
    timestamp. Only `created_at` is currently supported.
    """

    seconds: int
    """The number of seconds from the anchor point to the expiration.

    Select a value between `10` and `7200` (2 hours). This default to 600 seconds
    (10 minutes) if not specified.
    """


Session: TypeAlias = Union[RealtimeSessionCreateRequestParam, RealtimeTranscriptionSessionCreateRequestParam]
