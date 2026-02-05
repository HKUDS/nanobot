# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import TypeAlias

from ..responses.tool_choice_mcp import ToolChoiceMcp
from ..responses.tool_choice_options import ToolChoiceOptions
from ..responses.tool_choice_function import ToolChoiceFunction

__all__ = ["RealtimeToolChoiceConfig"]

RealtimeToolChoiceConfig: TypeAlias = Union[ToolChoiceOptions, ToolChoiceFunction, ToolChoiceMcp]
