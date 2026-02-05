# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from .image_url import ImageURL
from ...._models import BaseModel

__all__ = ["ImageURLContentBlock"]


class ImageURLContentBlock(BaseModel):
    """References an image URL in the content of a message."""

    image_url: ImageURL

    type: Literal["image_url"]
    """The type of the content part."""
