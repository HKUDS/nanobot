# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import TypeAlias

from .response_input_file_content_param import ResponseInputFileContentParam
from .response_input_text_content_param import ResponseInputTextContentParam
from .response_input_image_content_param import ResponseInputImageContentParam

__all__ = ["ResponseFunctionCallOutputItemParam"]

ResponseFunctionCallOutputItemParam: TypeAlias = Union[
    ResponseInputTextContentParam, ResponseInputImageContentParam, ResponseInputFileContentParam
]
