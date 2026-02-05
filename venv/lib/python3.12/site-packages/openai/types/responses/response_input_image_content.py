# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseInputImageContent"]


class ResponseInputImageContent(BaseModel):
    """An image input to the model.

    Learn about [image inputs](https://platform.openai.com/docs/guides/vision)
    """

    type: Literal["input_image"]
    """The type of the input item. Always `input_image`."""

    detail: Optional[Literal["low", "high", "auto"]] = None
    """The detail level of the image to be sent to the model.

    One of `high`, `low`, or `auto`. Defaults to `auto`.
    """

    file_id: Optional[str] = None
    """The ID of the file to be sent to the model."""

    image_url: Optional[str] = None
    """The URL of the image to be sent to the model.

    A fully qualified URL or base64 encoded image in a data URL.
    """
