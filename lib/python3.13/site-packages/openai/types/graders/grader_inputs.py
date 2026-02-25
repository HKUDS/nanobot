# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union, Optional
from typing_extensions import Literal, TypeAlias

from ..._models import BaseModel
from ..responses.response_input_text import ResponseInputText
from ..responses.response_input_audio import ResponseInputAudio

__all__ = ["GraderInputs", "GraderInputItem", "GraderInputItemOutputText", "GraderInputItemInputImage"]


class GraderInputItemOutputText(BaseModel):
    """A text output from the model."""

    text: str
    """The text output from the model."""

    type: Literal["output_text"]
    """The type of the output text. Always `output_text`."""


class GraderInputItemInputImage(BaseModel):
    """An image input block used within EvalItem content arrays."""

    image_url: str
    """The URL of the image input."""

    type: Literal["input_image"]
    """The type of the image input. Always `input_image`."""

    detail: Optional[str] = None
    """The detail level of the image to be sent to the model.

    One of `high`, `low`, or `auto`. Defaults to `auto`.
    """


GraderInputItem: TypeAlias = Union[
    str, ResponseInputText, GraderInputItemOutputText, GraderInputItemInputImage, ResponseInputAudio
]

GraderInputs: TypeAlias = List[GraderInputItem]
