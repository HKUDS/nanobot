# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ...._models import BaseModel
from .image_file import ImageFile

__all__ = ["ImageFileContentBlock"]


class ImageFileContentBlock(BaseModel):
    """
    References an image [File](https://platform.openai.com/docs/api-reference/files) in the content of a message.
    """

    image_file: ImageFile

    type: Literal["image_file"]
    """Always `image_file`."""
