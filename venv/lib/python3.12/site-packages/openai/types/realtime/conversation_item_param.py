# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import TypeAlias

from .realtime_mcp_tool_call_param import RealtimeMcpToolCallParam
from .realtime_mcp_list_tools_param import RealtimeMcpListToolsParam
from .realtime_mcp_approval_request_param import RealtimeMcpApprovalRequestParam
from .realtime_mcp_approval_response_param import RealtimeMcpApprovalResponseParam
from .realtime_conversation_item_user_message_param import RealtimeConversationItemUserMessageParam
from .realtime_conversation_item_function_call_param import RealtimeConversationItemFunctionCallParam
from .realtime_conversation_item_system_message_param import RealtimeConversationItemSystemMessageParam
from .realtime_conversation_item_assistant_message_param import RealtimeConversationItemAssistantMessageParam
from .realtime_conversation_item_function_call_output_param import RealtimeConversationItemFunctionCallOutputParam

__all__ = ["ConversationItemParam"]

ConversationItemParam: TypeAlias = Union[
    RealtimeConversationItemSystemMessageParam,
    RealtimeConversationItemUserMessageParam,
    RealtimeConversationItemAssistantMessageParam,
    RealtimeConversationItemFunctionCallParam,
    RealtimeConversationItemFunctionCallOutputParam,
    RealtimeMcpApprovalResponseParam,
    RealtimeMcpListToolsParam,
    RealtimeMcpToolCallParam,
    RealtimeMcpApprovalRequestParam,
]
