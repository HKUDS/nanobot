# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from ..._models import BaseModel

__all__ = ["RealtimeSessionClientSecret"]


class RealtimeSessionClientSecret(BaseModel):
    """Ephemeral key returned by the API."""

    expires_at: int
    """Timestamp for when the token expires.

    Currently, all tokens expire after one minute.
    """

    value: str
    """
    Ephemeral key usable in client environments to authenticate connections to the
    Realtime API. Use this in client-side environments rather than a standard API
    token, which should only be used server-side.
    """
