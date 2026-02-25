# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import List, Union
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from ..responses.response_input_text_param import ResponseInputTextParam
from ..responses.response_input_audio_param import ResponseInputAudioParam

__all__ = [
    "GraderInputsParam",
    "GraderInputsParamItem",
    "GraderInputsParamItemOutputText",
    "GraderInputsParamItemInputImage",
]


class GraderInputsParamItemOutputText(TypedDict, total=False):
    """A text output from the model."""

    text: Required[str]
    """The text output from the model."""

    type: Required[Literal["output_text"]]
    """The type of the output text. Always `output_text`."""


class GraderInputsParamItemInputImage(TypedDict, total=False):
    """An image input block used within EvalItem content arrays."""

    image_url: Required[str]
    """The URL of the image input."""

    type: Required[Literal["input_image"]]
    """The type of the image input. Always `input_image`."""

    detail: str
    """The detail level of the image to be sent to the model.

    One of `high`, `low`, or `auto`. Defaults to `auto`.
    """


GraderInputsParamItem: TypeAlias = Union[
    str,
    ResponseInputTextParam,
    GraderInputsParamItemOutputText,
    GraderInputsParamItemInputImage,
    ResponseInputAudioParam,
]

GraderInputsParam: TypeAlias = List[GraderInputsParamItem]
