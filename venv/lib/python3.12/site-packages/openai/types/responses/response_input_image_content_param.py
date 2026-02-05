# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Optional
from typing_extensions import Literal, Required, TypedDict

__all__ = ["ResponseInputImageContentParam"]


class ResponseInputImageContentParam(TypedDict, total=False):
    """An image input to the model.

    Learn about [image inputs](https://platform.openai.com/docs/guides/vision)
    """

    type: Required[Literal["input_image"]]
    """The type of the input item. Always `input_image`."""

    detail: Optional[Literal["low", "high", "auto"]]
    """The detail level of the image to be sent to the model.

    One of `high`, `low`, or `auto`. Defaults to `auto`.
    """

    file_id: Optional[str]
    """The ID of the file to be sent to the model."""

    image_url: Optional[str]
    """The URL of the image to be sent to the model.

    A fully qualified URL or base64 encoded image in a data URL.
    """
