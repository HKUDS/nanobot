# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .assistant_tool_choice_function import AssistantToolChoiceFunction

__all__ = ["AssistantToolChoice"]


class AssistantToolChoice(BaseModel):
    """Specifies a tool the model should use.

    Use to force the model to call a specific tool.
    """

    type: Literal["function", "code_interpreter", "file_search"]
    """The type of the tool. If type is `function`, the function name must be set"""

    function: Optional[AssistantToolChoiceFunction] = None
