# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import Annotated, TypeAlias

from ..._utils import PropertyInfo
from .realtime_mcp_tool_call import RealtimeMcpToolCall
from .realtime_mcp_list_tools import RealtimeMcpListTools
from .realtime_mcp_approval_request import RealtimeMcpApprovalRequest
from .realtime_mcp_approval_response import RealtimeMcpApprovalResponse
from .realtime_conversation_item_user_message import RealtimeConversationItemUserMessage
from .realtime_conversation_item_function_call import RealtimeConversationItemFunctionCall
from .realtime_conversation_item_system_message import RealtimeConversationItemSystemMessage
from .realtime_conversation_item_assistant_message import RealtimeConversationItemAssistantMessage
from .realtime_conversation_item_function_call_output import RealtimeConversationItemFunctionCallOutput

__all__ = ["ConversationItem"]

ConversationItem: TypeAlias = Annotated[
    Union[
        RealtimeConversationItemSystemMessage,
        RealtimeConversationItemUserMessage,
        RealtimeConversationItemAssistantMessage,
        RealtimeConversationItemFunctionCall,
        RealtimeConversationItemFunctionCallOutput,
        RealtimeMcpApprovalResponse,
        RealtimeMcpListTools,
        RealtimeMcpToolCall,
        RealtimeMcpApprovalRequest,
    ],
    PropertyInfo(discriminator="type"),
]
