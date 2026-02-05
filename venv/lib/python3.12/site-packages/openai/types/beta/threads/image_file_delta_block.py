# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ...._models import BaseModel
from .image_file_delta import ImageFileDelta

__all__ = ["ImageFileDeltaBlock"]


class ImageFileDeltaBlock(BaseModel):
    """
    References an image [File](https://platform.openai.com/docs/api-reference/files) in the content of a message.
    """

    index: int
    """The index of the content part in the message."""

    type: Literal["image_file"]
    """Always `image_file`."""

    image_file: Optional[ImageFileDelta] = None
