# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["InlineSkillSource"]


class InlineSkillSource(BaseModel):
    """Inline skill payload"""

    data: str
    """Base64-encoded skill zip bundle."""

    media_type: Literal["application/zip"]
    """The media type of the inline skill payload. Must be `application/zip`."""

    type: Literal["base64"]
    """The type of the inline skill source. Must be `base64`."""
