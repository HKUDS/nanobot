# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Optional
from typing_extensions import Literal, Required, TypedDict

__all__ = ["ResponseInputFileContentParam"]


class ResponseInputFileContentParam(TypedDict, total=False):
    """A file input to the model."""

    type: Required[Literal["input_file"]]
    """The type of the input item. Always `input_file`."""

    file_data: Optional[str]
    """The base64-encoded data of the file to be sent to the model."""

    file_id: Optional[str]
    """The ID of the file to be sent to the model."""

    file_url: Optional[str]
    """The URL of the file to be sent to the model."""

    filename: Optional[str]
    """The name of the file to be sent to the model."""
