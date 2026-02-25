# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ...._utils import PropertyInfo
from ...._models import BaseModel
from .chatkit_widget_item import ChatKitWidgetItem
from .chatkit_thread_user_message_item import ChatKitThreadUserMessageItem
from .chatkit_thread_assistant_message_item import ChatKitThreadAssistantMessageItem

__all__ = [
    "ChatKitThreadItemList",
    "Data",
    "DataChatKitClientToolCall",
    "DataChatKitTask",
    "DataChatKitTaskGroup",
    "DataChatKitTaskGroupTask",
]


class DataChatKitClientToolCall(BaseModel):
    """Record of a client side tool invocation initiated by the assistant."""

    id: str
    """Identifier of the thread item."""

    arguments: str
    """JSON-encoded arguments that were sent to the tool."""

    call_id: str
    """Identifier for the client tool call."""

    created_at: int
    """Unix timestamp (in seconds) for when the item was created."""

    name: str
    """Tool name that was invoked."""

    object: Literal["chatkit.thread_item"]
    """Type discriminator that is always `chatkit.thread_item`."""

    output: Optional[str] = None
    """JSON-encoded output captured from the tool.

    Defaults to null while execution is in progress.
    """

    status: Literal["in_progress", "completed"]
    """Execution status for the tool call."""

    thread_id: str
    """Identifier of the parent thread."""

    type: Literal["chatkit.client_tool_call"]
    """Type discriminator that is always `chatkit.client_tool_call`."""


class DataChatKitTask(BaseModel):
    """Task emitted by the workflow to show progress and status updates."""

    id: str
    """Identifier of the thread item."""

    created_at: int
    """Unix timestamp (in seconds) for when the item was created."""

    heading: Optional[str] = None
    """Optional heading for the task. Defaults to null when not provided."""

    object: Literal["chatkit.thread_item"]
    """Type discriminator that is always `chatkit.thread_item`."""

    summary: Optional[str] = None
    """Optional summary that describes the task. Defaults to null when omitted."""

    task_type: Literal["custom", "thought"]
    """Subtype for the task."""

    thread_id: str
    """Identifier of the parent thread."""

    type: Literal["chatkit.task"]
    """Type discriminator that is always `chatkit.task`."""


class DataChatKitTaskGroupTask(BaseModel):
    """Task entry that appears within a TaskGroup."""

    heading: Optional[str] = None
    """Optional heading for the grouped task. Defaults to null when not provided."""

    summary: Optional[str] = None
    """Optional summary that describes the grouped task.

    Defaults to null when omitted.
    """

    type: Literal["custom", "thought"]
    """Subtype for the grouped task."""


class DataChatKitTaskGroup(BaseModel):
    """Collection of workflow tasks grouped together in the thread."""

    id: str
    """Identifier of the thread item."""

    created_at: int
    """Unix timestamp (in seconds) for when the item was created."""

    object: Literal["chatkit.thread_item"]
    """Type discriminator that is always `chatkit.thread_item`."""

    tasks: List[DataChatKitTaskGroupTask]
    """Tasks included in the group."""

    thread_id: str
    """Identifier of the parent thread."""

    type: Literal["chatkit.task_group"]
    """Type discriminator that is always `chatkit.task_group`."""


Data: TypeAlias = Annotated[
    Union[
        ChatKitThreadUserMessageItem,
        ChatKitThreadAssistantMessageItem,
        ChatKitWidgetItem,
        DataChatKitClientToolCall,
        DataChatKitTask,
        DataChatKitTaskGroup,
    ],
    PropertyInfo(discriminator="type"),
]


class ChatKitThreadItemList(BaseModel):
    """A paginated list of thread items rendered for the ChatKit API."""

    data: List[Data]
    """A list of items"""

    first_id: Optional[str] = None
    """The ID of the first item in the list."""

    has_more: bool
    """Whether there are more items available."""

    last_id: Optional[str] = None
    """The ID of the last item in the list."""

    object: Literal["list"]
    """The type of object returned, must be `list`."""
