# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .text_content import TextContent
from .summary_text_content import SummaryTextContent
from .computer_screenshot_content import ComputerScreenshotContent
from ..responses.response_input_file import ResponseInputFile
from ..responses.response_input_text import ResponseInputText
from ..responses.response_input_image import ResponseInputImage
from ..responses.response_output_text import ResponseOutputText
from ..responses.response_output_refusal import ResponseOutputRefusal

__all__ = ["Message", "Content", "ContentReasoningText"]


class ContentReasoningText(BaseModel):
    """Reasoning text from the model."""

    text: str
    """The reasoning text from the model."""

    type: Literal["reasoning_text"]
    """The type of the reasoning text. Always `reasoning_text`."""


Content: TypeAlias = Annotated[
    Union[
        ResponseInputText,
        ResponseOutputText,
        TextContent,
        SummaryTextContent,
        ContentReasoningText,
        ResponseOutputRefusal,
        ResponseInputImage,
        ComputerScreenshotContent,
        ResponseInputFile,
    ],
    PropertyInfo(discriminator="type"),
]


class Message(BaseModel):
    """A message to or from the model."""

    id: str
    """The unique ID of the message."""

    content: List[Content]
    """The content of the message"""

    role: Literal["unknown", "user", "assistant", "system", "critic", "discriminator", "developer", "tool"]
    """The role of the message.

    One of `unknown`, `user`, `assistant`, `system`, `critic`, `discriminator`,
    `developer`, or `tool`.
    """

    status: Literal["in_progress", "completed", "incomplete"]
    """The status of item.

    One of `in_progress`, `completed`, or `incomplete`. Populated when items are
    returned via API.
    """

    type: Literal["message"]
    """The type of the message. Always set to `message`."""
