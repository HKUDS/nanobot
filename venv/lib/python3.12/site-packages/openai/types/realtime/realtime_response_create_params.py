# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union, Optional
from typing_extensions import Literal, TypeAlias

from ..._models import BaseModel
from ..shared.metadata import Metadata
from .conversation_item import ConversationItem
from .realtime_function_tool import RealtimeFunctionTool
from ..responses.response_prompt import ResponsePrompt
from ..responses.tool_choice_mcp import ToolChoiceMcp
from ..responses.tool_choice_options import ToolChoiceOptions
from ..responses.tool_choice_function import ToolChoiceFunction
from .realtime_response_create_mcp_tool import RealtimeResponseCreateMcpTool
from .realtime_response_create_audio_output import RealtimeResponseCreateAudioOutput

__all__ = ["RealtimeResponseCreateParams", "ToolChoice", "Tool"]

ToolChoice: TypeAlias = Union[ToolChoiceOptions, ToolChoiceFunction, ToolChoiceMcp]

Tool: TypeAlias = Union[RealtimeFunctionTool, RealtimeResponseCreateMcpTool]


class RealtimeResponseCreateParams(BaseModel):
    """Create a new Realtime response with these parameters"""

    audio: Optional[RealtimeResponseCreateAudioOutput] = None
    """Configuration for audio input and output."""

    conversation: Union[str, Literal["auto", "none"], None] = None
    """Controls which conversation the response is added to.

    Currently supports `auto` and `none`, with `auto` as the default value. The
    `auto` value means that the contents of the response will be added to the
    default conversation. Set this to `none` to create an out-of-band response which
    will not add items to default conversation.
    """

    input: Optional[List[ConversationItem]] = None
    """Input items to include in the prompt for the model.

    Using this field creates a new context for this Response instead of using the
    default conversation. An empty array `[]` will clear the context for this
    Response. Note that this can include references to items that previously
    appeared in the session using their id.
    """

    instructions: Optional[str] = None
    """The default system instructions (i.e.

    system message) prepended to model calls. This field allows the client to guide
    the model on desired responses. The model can be instructed on response content
    and format, (e.g. "be extremely succinct", "act friendly", "here are examples of
    good responses") and on audio behavior (e.g. "talk quickly", "inject emotion
    into your voice", "laugh frequently"). The instructions are not guaranteed to be
    followed by the model, but they provide guidance to the model on the desired
    behavior. Note that the server sets default instructions which will be used if
    this field is not set and are visible in the `session.created` event at the
    start of the session.
    """

    max_output_tokens: Union[int, Literal["inf"], None] = None
    """
    Maximum number of output tokens for a single assistant response, inclusive of
    tool calls. Provide an integer between 1 and 4096 to limit output tokens, or
    `inf` for the maximum available tokens for a given model. Defaults to `inf`.
    """

    metadata: Optional[Metadata] = None
    """Set of 16 key-value pairs that can be attached to an object.

    This can be useful for storing additional information about the object in a
    structured format, and querying for objects via API or the dashboard.

    Keys are strings with a maximum length of 64 characters. Values are strings with
    a maximum length of 512 characters.
    """

    output_modalities: Optional[List[Literal["text", "audio"]]] = None
    """
    The set of modalities the model used to respond, currently the only possible
    values are `[\"audio\"]`, `[\"text\"]`. Audio output always include a text
    transcript. Setting the output to mode `text` will disable audio output from the
    model.
    """

    prompt: Optional[ResponsePrompt] = None
    """
    Reference to a prompt template and its variables.
    [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).
    """

    tool_choice: Optional[ToolChoice] = None
    """How the model chooses tools.

    Provide one of the string modes or force a specific function/MCP tool.
    """

    tools: Optional[List[Tool]] = None
    """Tools available to the model."""
