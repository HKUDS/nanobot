from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Final, Generic, Literal, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, FileUrl, RootModel
from pydantic.networks import AnyUrl, UrlConstraints
from typing_extensions import deprecated

"""
Model Context Protocol bindings for Python

These bindings were generated from https://github.com/modelcontextprotocol/specification,
using Claude, with a prompt something like the following:

Generate idiomatic Python bindings for this schema for MCP, or the "Model Context
Protocol." The schema is defined in TypeScript, but there's also a JSON Schema version
for reference.

* For the bindings, let's use Pydantic V2 models.
* Each model should allow extra fields everywhere, by specifying `model_config =
  ConfigDict(extra='allow')`. Do this in every case, instead of a custom base class.
* Union types should be represented with a Pydantic `RootModel`.
* Define additional model classes instead of using dictionaries. Do this even if they're
  not separate types in the schema.
"""

LATEST_PROTOCOL_VERSION = "2025-11-25"

"""
The default negotiated version of the Model Context Protocol when no version is specified.
We need this to satisfy the MCP specification, which requires the server to assume a
specific version if none is provided by the client. See section "Protocol Version Header" at
https://modelcontextprotocol.io/specification
"""
DEFAULT_NEGOTIATED_VERSION = "2025-03-26"

ProgressToken = str | int
Cursor = str
Role = Literal["user", "assistant"]
RequestId = Annotated[int, Field(strict=True)] | str
AnyFunction: TypeAlias = Callable[..., Any]

TaskExecutionMode = Literal["forbidden", "optional", "required"]
TASK_FORBIDDEN: Final[Literal["forbidden"]] = "forbidden"
TASK_OPTIONAL: Final[Literal["optional"]] = "optional"
TASK_REQUIRED: Final[Literal["required"]] = "required"


class TaskMetadata(BaseModel):
    """
    Metadata for augmenting a request with task execution.
    Include this in the `task` field of the request parameters.
    """

    model_config = ConfigDict(extra="allow")

    ttl: Annotated[int, Field(strict=True)] | None = None
    """Requested duration in milliseconds to retain task from creation."""


class RequestParams(BaseModel):
    class Meta(BaseModel):
        progressToken: ProgressToken | None = None
        """
        If specified, the caller requests out-of-band progress notifications for
        this request (as represented by notifications/progress). The value of this
        parameter is an opaque token that will be attached to any subsequent
        notifications. The receiver is not obligated to provide these notifications.
        """

        model_config = ConfigDict(extra="allow")

    task: TaskMetadata | None = None
    """
    If specified, the caller is requesting task-augmented execution for this request.
    The request will return a CreateTaskResult immediately, and the actual result can be
    retrieved later via tasks/result.

    Task augmentation is subject to capability negotiation - receivers MUST declare support
    for task augmentation of specific request types in their capabilities.
    """

    meta: Meta | None = Field(alias="_meta", default=None)


class PaginatedRequestParams(RequestParams):
    cursor: Cursor | None = None
    """
    An opaque token representing the current pagination position.
    If provided, the server should return results starting after this cursor.
    """


class NotificationParams(BaseModel):
    class Meta(BaseModel):
        model_config = ConfigDict(extra="allow")

    meta: Meta | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """


RequestParamsT = TypeVar("RequestParamsT", bound=RequestParams | dict[str, Any] | None)
NotificationParamsT = TypeVar("NotificationParamsT", bound=NotificationParams | dict[str, Any] | None)
MethodT = TypeVar("MethodT", bound=str)


class Request(BaseModel, Generic[RequestParamsT, MethodT]):
    """Base class for JSON-RPC requests."""

    method: MethodT
    params: RequestParamsT
    model_config = ConfigDict(extra="allow")


class PaginatedRequest(Request[PaginatedRequestParams | None, MethodT], Generic[MethodT]):
    """Base class for paginated requests,
    matching the schema's PaginatedRequest interface."""

    params: PaginatedRequestParams | None = None


class Notification(BaseModel, Generic[NotificationParamsT, MethodT]):
    """Base class for JSON-RPC notifications."""

    method: MethodT
    params: NotificationParamsT
    model_config = ConfigDict(extra="allow")


class Result(BaseModel):
    """Base class for JSON-RPC results."""

    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class PaginatedResult(Result):
    nextCursor: Cursor | None = None
    """
    An opaque token representing the pagination position after the last returned result.
    If present, there may be more results available.
    """


class JSONRPCRequest(Request[dict[str, Any] | None, str]):
    """A request that expects a response."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    method: str
    params: dict[str, Any] | None = None


class JSONRPCNotification(Notification[dict[str, Any] | None, str]):
    """A notification which does not expect a response."""

    jsonrpc: Literal["2.0"]
    params: dict[str, Any] | None = None


class JSONRPCResponse(BaseModel):
    """A successful (non-error) response to a request."""

    jsonrpc: Literal["2.0"]
    id: RequestId
    result: dict[str, Any]
    model_config = ConfigDict(extra="allow")


# MCP-specific error codes in the range [-32000, -32099]
URL_ELICITATION_REQUIRED = -32042
"""Error code indicating that a URL mode elicitation is required before the request can be processed."""

# SDK error codes
CONNECTION_CLOSED = -32000
# REQUEST_TIMEOUT = -32001  # the typescript sdk uses this

# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ErrorData(BaseModel):
    """Error information for JSON-RPC error responses."""

    code: int
    """The error type that occurred."""

    message: str
    """
    A short description of the error. The message SHOULD be limited to a concise single
    sentence.
    """

    data: Any | None = None
    """
    Additional information about the error. The value of this member is defined by the
    sender (e.g. detailed error information, nested errors etc.).
    """

    model_config = ConfigDict(extra="allow")


class JSONRPCError(BaseModel):
    """A response to a request that indicates an error occurred."""

    jsonrpc: Literal["2.0"]
    id: str | int
    error: ErrorData
    model_config = ConfigDict(extra="allow")


class JSONRPCMessage(RootModel[JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError]):
    pass


class EmptyResult(Result):
    """A response that indicates success but carries no data."""


class BaseMetadata(BaseModel):
    """Base class for entities with name and optional title fields."""

    name: str
    """The programmatic name of the entity."""

    title: str | None = None
    """
    Intended for UI and end-user contexts — optimized to be human-readable and easily understood,
    even by those unfamiliar with domain-specific terminology.

    If not provided, the name should be used for display (except for Tool,
    where `annotations.title` should be given precedence over using `name`,
    if present).
    """


class Icon(BaseModel):
    """An icon for display in user interfaces."""

    src: str
    """URL or data URI for the icon."""

    mimeType: str | None = None
    """Optional MIME type for the icon."""

    sizes: list[str] | None = None
    """Optional list of strings specifying icon dimensions (e.g., ["48x48", "96x96"])."""

    model_config = ConfigDict(extra="allow")


class Implementation(BaseMetadata):
    """Describes the name and version of an MCP implementation."""

    version: str

    websiteUrl: str | None = None
    """An optional URL of the website for this implementation."""

    icons: list[Icon] | None = None
    """An optional list of icons for this implementation."""

    model_config = ConfigDict(extra="allow")


class RootsCapability(BaseModel):
    """Capability for root operations."""

    listChanged: bool | None = None
    """Whether the client supports notifications for changes to the roots list."""
    model_config = ConfigDict(extra="allow")


class SamplingContextCapability(BaseModel):
    """
    Capability for context inclusion during sampling.

    Indicates support for non-'none' values in the includeContext parameter.
    SOFT-DEPRECATED: New implementations should use tools parameter instead.
    """

    model_config = ConfigDict(extra="allow")


class SamplingToolsCapability(BaseModel):
    """
    Capability indicating support for tool calling during sampling.

    When present in ClientCapabilities.sampling, indicates that the client
    supports the tools and toolChoice parameters in sampling requests.
    """

    model_config = ConfigDict(extra="allow")


class FormElicitationCapability(BaseModel):
    """Capability for form mode elicitation."""

    model_config = ConfigDict(extra="allow")


class UrlElicitationCapability(BaseModel):
    """Capability for URL mode elicitation."""

    model_config = ConfigDict(extra="allow")


class ElicitationCapability(BaseModel):
    """Capability for elicitation operations.

    Clients must support at least one mode (form or url).
    """

    form: FormElicitationCapability | None = None
    """Present if the client supports form mode elicitation."""

    url: UrlElicitationCapability | None = None
    """Present if the client supports URL mode elicitation."""

    model_config = ConfigDict(extra="allow")


class SamplingCapability(BaseModel):
    """
    Sampling capability structure, allowing fine-grained capability advertisement.
    """

    context: SamplingContextCapability | None = None
    """
    Present if the client supports non-'none' values for includeContext parameter.
    SOFT-DEPRECATED: New implementations should use tools parameter instead.
    """
    tools: SamplingToolsCapability | None = None
    """
    Present if the client supports tools and toolChoice parameters in sampling requests.
    Presence indicates full tool calling support during sampling.
    """
    model_config = ConfigDict(extra="allow")


class TasksListCapability(BaseModel):
    """Capability for tasks listing operations."""

    model_config = ConfigDict(extra="allow")


class TasksCancelCapability(BaseModel):
    """Capability for tasks cancel operations."""

    model_config = ConfigDict(extra="allow")


class TasksCreateMessageCapability(BaseModel):
    """Capability for tasks create messages."""

    model_config = ConfigDict(extra="allow")


class TasksSamplingCapability(BaseModel):
    """Capability for tasks sampling operations."""

    model_config = ConfigDict(extra="allow")

    createMessage: TasksCreateMessageCapability | None = None


class TasksCreateElicitationCapability(BaseModel):
    """Capability for tasks create elicitation operations."""

    model_config = ConfigDict(extra="allow")


class TasksElicitationCapability(BaseModel):
    """Capability for tasks elicitation operations."""

    model_config = ConfigDict(extra="allow")

    create: TasksCreateElicitationCapability | None = None


class ClientTasksRequestsCapability(BaseModel):
    """Capability for tasks requests operations."""

    model_config = ConfigDict(extra="allow")

    sampling: TasksSamplingCapability | None = None

    elicitation: TasksElicitationCapability | None = None


class ClientTasksCapability(BaseModel):
    """Capability for client tasks operations."""

    model_config = ConfigDict(extra="allow")

    list: TasksListCapability | None = None
    """Whether this client supports tasks/list."""

    cancel: TasksCancelCapability | None = None
    """Whether this client supports tasks/cancel."""

    requests: ClientTasksRequestsCapability | None = None
    """Specifies which request types can be augmented with tasks."""


class ClientCapabilities(BaseModel):
    """Capabilities a client may support."""

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the client supports."""
    sampling: SamplingCapability | None = None
    """
    Present if the client supports sampling from an LLM.
    Can contain fine-grained capabilities like context and tools support.
    """
    elicitation: ElicitationCapability | None = None
    """Present if the client supports elicitation from the user."""
    roots: RootsCapability | None = None
    """Present if the client supports listing roots."""
    tasks: ClientTasksCapability | None = None
    """Present if the client supports task-augmented requests."""

    model_config = ConfigDict(extra="allow")


class PromptsCapability(BaseModel):
    """Capability for prompts operations."""

    listChanged: bool | None = None
    """Whether this server supports notifications for changes to the prompt list."""
    model_config = ConfigDict(extra="allow")


class ResourcesCapability(BaseModel):
    """Capability for resources operations."""

    subscribe: bool | None = None
    """Whether this server supports subscribing to resource updates."""
    listChanged: bool | None = None
    """Whether this server supports notifications for changes to the resource list."""
    model_config = ConfigDict(extra="allow")


class ToolsCapability(BaseModel):
    """Capability for tools operations."""

    listChanged: bool | None = None
    """Whether this server supports notifications for changes to the tool list."""
    model_config = ConfigDict(extra="allow")


class LoggingCapability(BaseModel):
    """Capability for logging operations."""

    model_config = ConfigDict(extra="allow")


class CompletionsCapability(BaseModel):
    """Capability for completions operations."""

    model_config = ConfigDict(extra="allow")


class TasksCallCapability(BaseModel):
    """Capability for tasks call operations."""

    model_config = ConfigDict(extra="allow")


class TasksToolsCapability(BaseModel):
    """Capability for tasks tools operations."""

    model_config = ConfigDict(extra="allow")
    call: TasksCallCapability | None = None


class ServerTasksRequestsCapability(BaseModel):
    """Capability for tasks requests operations."""

    model_config = ConfigDict(extra="allow")

    tools: TasksToolsCapability | None = None


class ServerTasksCapability(BaseModel):
    """Capability for server tasks operations."""

    model_config = ConfigDict(extra="allow")

    list: TasksListCapability | None = None
    cancel: TasksCancelCapability | None = None
    requests: ServerTasksRequestsCapability | None = None


class ServerCapabilities(BaseModel):
    """Capabilities that a server may support."""

    experimental: dict[str, dict[str, Any]] | None = None
    """Experimental, non-standard capabilities that the server supports."""
    logging: LoggingCapability | None = None
    """Present if the server supports sending log messages to the client."""
    prompts: PromptsCapability | None = None
    """Present if the server offers any prompt templates."""
    resources: ResourcesCapability | None = None
    """Present if the server offers any resources to read."""
    tools: ToolsCapability | None = None
    """Present if the server offers any tools to call."""
    completions: CompletionsCapability | None = None
    """Present if the server offers autocompletion suggestions for prompts and resources."""
    tasks: ServerTasksCapability | None = None
    """Present if the server supports task-augmented requests."""
    model_config = ConfigDict(extra="allow")


TaskStatus = Literal["working", "input_required", "completed", "failed", "cancelled"]

# Task status constants
TASK_STATUS_WORKING: Final[Literal["working"]] = "working"
TASK_STATUS_INPUT_REQUIRED: Final[Literal["input_required"]] = "input_required"
TASK_STATUS_COMPLETED: Final[Literal["completed"]] = "completed"
TASK_STATUS_FAILED: Final[Literal["failed"]] = "failed"
TASK_STATUS_CANCELLED: Final[Literal["cancelled"]] = "cancelled"


class RelatedTaskMetadata(BaseModel):
    """
    Metadata for associating messages with a task.

    Include this in the `_meta` field under the key `io.modelcontextprotocol/related-task`.
    """

    model_config = ConfigDict(extra="allow")
    taskId: str
    """The task identifier this message is associated with."""


class Task(BaseModel):
    """Data associated with a task."""

    model_config = ConfigDict(extra="allow")

    taskId: str
    """The task identifier."""

    status: TaskStatus
    """Current task state."""

    statusMessage: str | None = None
    """  
    Optional human-readable message describing the current task state.
    This can provide context for any status, including:
    - Reasons for "cancelled" status
    - Summaries for "completed" status
    - Diagnostic information for "failed" status (e.g., error details, what went wrong)
    """

    createdAt: datetime  # Pydantic will enforce ISO 8601 and re-serialize as a string later
    """ISO 8601 timestamp when the task was created."""

    lastUpdatedAt: datetime
    """ISO 8601 timestamp when the task was last updated."""

    ttl: Annotated[int, Field(strict=True)] | None
    """Actual retention duration from creation in milliseconds, null for unlimited."""

    pollInterval: Annotated[int, Field(strict=True)] | None = None
    """Suggested polling interval in milliseconds."""


class CreateTaskResult(Result):
    """A response to a task-augmented request."""

    task: Task


class GetTaskRequestParams(RequestParams):
    model_config = ConfigDict(extra="allow")
    taskId: str
    """The task identifier to query."""


class GetTaskRequest(Request[GetTaskRequestParams, Literal["tasks/get"]]):
    """A request to retrieve the state of a task."""

    method: Literal["tasks/get"] = "tasks/get"

    params: GetTaskRequestParams


class GetTaskResult(Result, Task):
    """The response to a tasks/get request."""


class GetTaskPayloadRequestParams(RequestParams):
    model_config = ConfigDict(extra="allow")

    taskId: str
    """The task identifier to retrieve results for."""


class GetTaskPayloadRequest(Request[GetTaskPayloadRequestParams, Literal["tasks/result"]]):
    """A request to retrieve the result of a completed task."""

    method: Literal["tasks/result"] = "tasks/result"
    params: GetTaskPayloadRequestParams


class GetTaskPayloadResult(Result):
    """
    The response to a tasks/result request.
    The structure matches the result type of the original request.
    For example, a tools/call task would return the CallToolResult structure.
    """


class CancelTaskRequestParams(RequestParams):
    model_config = ConfigDict(extra="allow")

    taskId: str
    """The task identifier to cancel."""


class CancelTaskRequest(Request[CancelTaskRequestParams, Literal["tasks/cancel"]]):
    """A request to cancel a task."""

    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: CancelTaskRequestParams


class CancelTaskResult(Result, Task):
    """The response to a tasks/cancel request."""


class ListTasksRequest(PaginatedRequest[Literal["tasks/list"]]):
    """A request to retrieve a list of tasks."""

    method: Literal["tasks/list"] = "tasks/list"


class ListTasksResult(PaginatedResult):
    """The response to a tasks/list request."""

    tasks: list[Task]


class TaskStatusNotificationParams(NotificationParams, Task):
    """Parameters for a `notifications/tasks/status` notification."""


class TaskStatusNotification(Notification[TaskStatusNotificationParams, Literal["notifications/tasks/status"]]):
    """
    An optional notification from the receiver to the requestor, informing them that a task's status has changed.
    Receivers are not required to send these notifications
    """

    method: Literal["notifications/tasks/status"] = "notifications/tasks/status"
    params: TaskStatusNotificationParams


class InitializeRequestParams(RequestParams):
    """Parameters for the initialize request."""

    protocolVersion: str | int
    """The latest version of the Model Context Protocol that the client supports."""
    capabilities: ClientCapabilities
    clientInfo: Implementation
    model_config = ConfigDict(extra="allow")


class InitializeRequest(Request[InitializeRequestParams, Literal["initialize"]]):
    """
    This request is sent from the client to the server when it first connects, asking it
    to begin initialization.
    """

    method: Literal["initialize"] = "initialize"
    params: InitializeRequestParams


class InitializeResult(Result):
    """After receiving an initialize request from the client, the server sends this."""

    protocolVersion: str | int
    """The version of the Model Context Protocol that the server wants to use."""
    capabilities: ServerCapabilities
    serverInfo: Implementation
    instructions: str | None = None
    """Instructions describing how to use the server and its features."""


class InitializedNotification(Notification[NotificationParams | None, Literal["notifications/initialized"]]):
    """
    This notification is sent from the client to the server after initialization has
    finished.
    """

    method: Literal["notifications/initialized"] = "notifications/initialized"
    params: NotificationParams | None = None


class PingRequest(Request[RequestParams | None, Literal["ping"]]):
    """
    A ping, issued by either the server or the client, to check that the other party is
    still alive.
    """

    method: Literal["ping"] = "ping"
    params: RequestParams | None = None


class ProgressNotificationParams(NotificationParams):
    """Parameters for progress notifications."""

    progressToken: ProgressToken
    """
    The progress token which was given in the initial request, used to associate this
    notification with the request that is proceeding.
    """
    progress: float
    """
    The progress thus far. This should increase every time progress is made, even if the
    total is unknown.
    """
    total: float | None = None
    """Total number of items to process (or total progress required), if known."""
    message: str | None = None
    """
    Message related to progress. This should provide relevant human readable
    progress information.
    """
    model_config = ConfigDict(extra="allow")


class ProgressNotification(Notification[ProgressNotificationParams, Literal["notifications/progress"]]):
    """
    An out-of-band notification used to inform the receiver of a progress update for a
    long-running request.
    """

    method: Literal["notifications/progress"] = "notifications/progress"
    params: ProgressNotificationParams


class ListResourcesRequest(PaginatedRequest[Literal["resources/list"]]):
    """Sent from the client to request a list of resources the server has."""

    method: Literal["resources/list"] = "resources/list"


class Annotations(BaseModel):
    audience: list[Role] | None = None
    priority: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    model_config = ConfigDict(extra="allow")


class Resource(BaseMetadata):
    """A known resource that the server is capable of reading."""

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """The URI of this resource."""
    description: str | None = None
    """A description of what this resource represents."""
    mimeType: str | None = None
    """The MIME type of this resource, if known."""
    size: int | None = None
    """
    The size of the raw resource content, in bytes (i.e., before base64 encoding
    or any tokenization), if known.

    This can be used by Hosts to display file sizes and estimate context window usage.
    """
    icons: list[Icon] | None = None
    """An optional list of icons for this resource."""
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class ResourceTemplate(BaseMetadata):
    """A template description for resources available on the server."""

    uriTemplate: str
    """
    A URI template (according to RFC 6570) that can be used to construct resource
    URIs.
    """
    description: str | None = None
    """A human-readable description of what this template is for."""
    mimeType: str | None = None
    """
    The MIME type for all resources that match this template. This should only be
    included if all resources matching this template have the same type.
    """
    icons: list[Icon] | None = None
    """An optional list of icons for this resource template."""
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class ListResourcesResult(PaginatedResult):
    """The server's response to a resources/list request from the client."""

    resources: list[Resource]


class ListResourceTemplatesRequest(PaginatedRequest[Literal["resources/templates/list"]]):
    """Sent from the client to request a list of resource templates the server has."""

    method: Literal["resources/templates/list"] = "resources/templates/list"


class ListResourceTemplatesResult(PaginatedResult):
    """The server's response to a resources/templates/list request from the client."""

    resourceTemplates: list[ResourceTemplate]


class ReadResourceRequestParams(RequestParams):
    """Parameters for reading a resource."""

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """
    The URI of the resource to read. The URI can use any protocol; it is up to the
    server how to interpret it.
    """
    model_config = ConfigDict(extra="allow")


class ReadResourceRequest(Request[ReadResourceRequestParams, Literal["resources/read"]]):
    """Sent from the client to the server, to read a specific resource URI."""

    method: Literal["resources/read"] = "resources/read"
    params: ReadResourceRequestParams


class ResourceContents(BaseModel):
    """The contents of a specific resource or sub-resource."""

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """The URI of this resource."""
    mimeType: str | None = None
    """The MIME type of this resource, if known."""
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class TextResourceContents(ResourceContents):
    """Text contents of a resource."""

    text: str
    """
    The text of the item. This must only be set if the item can actually be represented
    as text (not binary data).
    """


class BlobResourceContents(ResourceContents):
    """Binary contents of a resource."""

    blob: str
    """A base64-encoded string representing the binary data of the item."""


class ReadResourceResult(Result):
    """The server's response to a resources/read request from the client."""

    contents: list[TextResourceContents | BlobResourceContents]


class ResourceListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/resources/list_changed"]]
):
    """
    An optional notification from the server to the client, informing it that the list
    of resources it can read from has changed.
    """

    method: Literal["notifications/resources/list_changed"] = "notifications/resources/list_changed"
    params: NotificationParams | None = None


class SubscribeRequestParams(RequestParams):
    """Parameters for subscribing to a resource."""

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """
    The URI of the resource to subscribe to. The URI can use any protocol; it is up to
    the server how to interpret it.
    """
    model_config = ConfigDict(extra="allow")


class SubscribeRequest(Request[SubscribeRequestParams, Literal["resources/subscribe"]]):
    """
    Sent from the client to request resources/updated notifications from the server
    whenever a particular resource changes.
    """

    method: Literal["resources/subscribe"] = "resources/subscribe"
    params: SubscribeRequestParams


class UnsubscribeRequestParams(RequestParams):
    """Parameters for unsubscribing from a resource."""

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """The URI of the resource to unsubscribe from."""
    model_config = ConfigDict(extra="allow")


class UnsubscribeRequest(Request[UnsubscribeRequestParams, Literal["resources/unsubscribe"]]):
    """
    Sent from the client to request cancellation of resources/updated notifications from
    the server.
    """

    method: Literal["resources/unsubscribe"] = "resources/unsubscribe"
    params: UnsubscribeRequestParams


class ResourceUpdatedNotificationParams(NotificationParams):
    """Parameters for resource update notifications."""

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)]
    """
    The URI of the resource that has been updated. This might be a sub-resource of the
    one that the client actually subscribed to.
    """
    model_config = ConfigDict(extra="allow")


class ResourceUpdatedNotification(
    Notification[ResourceUpdatedNotificationParams, Literal["notifications/resources/updated"]]
):
    """
    A notification from the server to the client, informing it that a resource has
    changed and may need to be read again.
    """

    method: Literal["notifications/resources/updated"] = "notifications/resources/updated"
    params: ResourceUpdatedNotificationParams


class ListPromptsRequest(PaginatedRequest[Literal["prompts/list"]]):
    """Sent from the client to request a list of prompts and prompt templates."""

    method: Literal["prompts/list"] = "prompts/list"


class PromptArgument(BaseModel):
    """An argument for a prompt template."""

    name: str
    """The name of the argument."""
    description: str | None = None
    """A human-readable description of the argument."""
    required: bool | None = None
    """Whether this argument must be provided."""
    model_config = ConfigDict(extra="allow")


class Prompt(BaseMetadata):
    """A prompt or prompt template that the server offers."""

    description: str | None = None
    """An optional description of what this prompt provides."""
    arguments: list[PromptArgument] | None = None
    """A list of arguments to use for templating the prompt."""
    icons: list[Icon] | None = None
    """An optional list of icons for this prompt."""
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class ListPromptsResult(PaginatedResult):
    """The server's response to a prompts/list request from the client."""

    prompts: list[Prompt]


class GetPromptRequestParams(RequestParams):
    """Parameters for getting a prompt."""

    name: str
    """The name of the prompt or prompt template."""
    arguments: dict[str, str] | None = None
    """Arguments to use for templating the prompt."""
    model_config = ConfigDict(extra="allow")


class GetPromptRequest(Request[GetPromptRequestParams, Literal["prompts/get"]]):
    """Used by the client to get a prompt provided by the server."""

    method: Literal["prompts/get"] = "prompts/get"
    params: GetPromptRequestParams


class TextContent(BaseModel):
    """Text content for a message."""

    type: Literal["text"]
    text: str
    """The text content of the message."""
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class ImageContent(BaseModel):
    """Image content for a message."""

    type: Literal["image"]
    data: str
    """The base64-encoded image data."""
    mimeType: str
    """
    The MIME type of the image. Different providers may support different
    image types.
    """
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class AudioContent(BaseModel):
    """Audio content for a message."""

    type: Literal["audio"]
    data: str
    """The base64-encoded audio data."""
    mimeType: str
    """
    The MIME type of the audio. Different providers may support different
    audio types.
    """
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class ToolUseContent(BaseModel):
    """
    Content representing an assistant's request to invoke a tool.

    This content type appears in assistant messages when the LLM wants to call a tool
    during sampling. The server should execute the tool and return a ToolResultContent
    in the next user message.
    """

    type: Literal["tool_use"]
    """Discriminator for tool use content."""

    name: str
    """The name of the tool to invoke. Must match a tool name from the request's tools array."""

    id: str
    """Unique identifier for this tool call, used to correlate with ToolResultContent."""

    input: dict[str, Any]
    """Arguments to pass to the tool. Must conform to the tool's inputSchema."""

    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class ToolResultContent(BaseModel):
    """
    Content representing the result of a tool execution.

    This content type appears in user messages as a response to a ToolUseContent
    from the assistant. It contains the output of executing the requested tool.
    """

    type: Literal["tool_result"]
    """Discriminator for tool result content."""

    toolUseId: str
    """The unique identifier that corresponds to the tool call's id field."""

    content: list["ContentBlock"] = []
    """
    A list of content objects representing the tool result.
    Defaults to empty list if not provided.
    """

    structuredContent: dict[str, Any] | None = None
    """
    Optional structured tool output that matches the tool's outputSchema (if defined).
    """

    isError: bool | None = None
    """Whether the tool execution resulted in an error."""

    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


SamplingMessageContentBlock: TypeAlias = TextContent | ImageContent | AudioContent | ToolUseContent | ToolResultContent
"""Content block types allowed in sampling messages."""

SamplingContent: TypeAlias = TextContent | ImageContent | AudioContent
"""Basic content types for sampling responses (without tool use).
Used for backwards-compatible CreateMessageResult when tools are not used."""


class SamplingMessage(BaseModel):
    """Describes a message issued to or received from an LLM API."""

    role: Role
    content: SamplingMessageContentBlock | list[SamplingMessageContentBlock]
    """
    Message content. Can be a single content block or an array of content blocks
    for multi-modal messages and tool interactions.
    """
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")

    @property
    def content_as_list(self) -> list[SamplingMessageContentBlock]:
        """Returns the content as a list of content blocks, regardless of whether
        it was originally a single block or a list."""
        return self.content if isinstance(self.content, list) else [self.content]


class EmbeddedResource(BaseModel):
    """
    The contents of a resource, embedded into a prompt or tool call result.

    It is up to the client how best to render embedded resources for the benefit
    of the LLM and/or the user.
    """

    type: Literal["resource"]
    resource: TextResourceContents | BlobResourceContents
    annotations: Annotations | None = None
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class ResourceLink(Resource):
    """
    A resource that the server is capable of reading, included in a prompt or tool call result.

    Note: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.
    """

    type: Literal["resource_link"]


ContentBlock = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource
"""A content block that can be used in prompts and tool results."""

Content: TypeAlias = ContentBlock
# """DEPRECATED: Content is deprecated, you should use ContentBlock directly."""


class PromptMessage(BaseModel):
    """Describes a message returned as part of a prompt."""

    role: Role
    content: ContentBlock
    model_config = ConfigDict(extra="allow")


class GetPromptResult(Result):
    """The server's response to a prompts/get request from the client."""

    description: str | None = None
    """An optional description for the prompt."""
    messages: list[PromptMessage]


class PromptListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/prompts/list_changed"]]
):
    """
    An optional notification from the server to the client, informing it that the list
    of prompts it offers has changed.
    """

    method: Literal["notifications/prompts/list_changed"] = "notifications/prompts/list_changed"
    params: NotificationParams | None = None


class ListToolsRequest(PaginatedRequest[Literal["tools/list"]]):
    """Sent from the client to request a list of tools the server has."""

    method: Literal["tools/list"] = "tools/list"


class ToolAnnotations(BaseModel):
    """
    Additional properties describing a Tool to clients.

    NOTE: all properties in ToolAnnotations are **hints**.
    They are not guaranteed to provide a faithful description of
    tool behavior (including descriptive properties like `title`).

    Clients should never make tool use decisions based on ToolAnnotations
    received from untrusted servers.
    """

    title: str | None = None
    """A human-readable title for the tool."""

    readOnlyHint: bool | None = None
    """
    If true, the tool does not modify its environment.
    Default: false
    """

    destructiveHint: bool | None = None
    """
    If true, the tool may perform destructive updates to its environment.
    If false, the tool performs only additive updates.
    (This property is meaningful only when `readOnlyHint == false`)
    Default: true
    """

    idempotentHint: bool | None = None
    """
    If true, calling the tool repeatedly with the same arguments
    will have no additional effect on the its environment.
    (This property is meaningful only when `readOnlyHint == false`)
    Default: false
    """

    openWorldHint: bool | None = None
    """
    If true, this tool may interact with an "open world" of external
    entities. If false, the tool's domain of interaction is closed.
    For example, the world of a web search tool is open, whereas that
    of a memory tool is not.
    Default: true
    """

    model_config = ConfigDict(extra="allow")


class ToolExecution(BaseModel):
    """Execution-related properties for a tool."""

    model_config = ConfigDict(extra="allow")

    taskSupport: TaskExecutionMode | None = None
    """
    Indicates whether this tool supports task-augmented execution.
    This allows clients to handle long-running operations through polling
    the task system.

    - "forbidden": Tool does not support task-augmented execution (default when absent)
    - "optional": Tool may support task-augmented execution
    - "required": Tool requires task-augmented execution

    Default: "forbidden"
    """


class Tool(BaseMetadata):
    """Definition for a tool the client can call."""

    description: str | None = None
    """A human-readable description of the tool."""
    inputSchema: dict[str, Any]
    """A JSON Schema object defining the expected parameters for the tool."""
    outputSchema: dict[str, Any] | None = None
    """
    An optional JSON Schema object defining the structure of the tool's output
    returned in the structuredContent field of a CallToolResult.
    """
    icons: list[Icon] | None = None
    """An optional list of icons for this tool."""
    annotations: ToolAnnotations | None = None
    """Optional additional tool information."""
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """

    execution: ToolExecution | None = None

    model_config = ConfigDict(extra="allow")


class ListToolsResult(PaginatedResult):
    """The server's response to a tools/list request from the client."""

    tools: list[Tool]


class CallToolRequestParams(RequestParams):
    """Parameters for calling a tool."""

    name: str
    arguments: dict[str, Any] | None = None
    model_config = ConfigDict(extra="allow")


class CallToolRequest(Request[CallToolRequestParams, Literal["tools/call"]]):
    """Used by the client to invoke a tool provided by the server."""

    method: Literal["tools/call"] = "tools/call"
    params: CallToolRequestParams


class CallToolResult(Result):
    """The server's response to a tool call."""

    content: list[ContentBlock]
    structuredContent: dict[str, Any] | None = None
    """An optional JSON object that represents the structured result of the tool call."""
    isError: bool = False


class ToolListChangedNotification(Notification[NotificationParams | None, Literal["notifications/tools/list_changed"]]):
    """
    An optional notification from the server to the client, informing it that the list
    of tools it offers has changed.
    """

    method: Literal["notifications/tools/list_changed"] = "notifications/tools/list_changed"
    params: NotificationParams | None = None


LoggingLevel = Literal["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]


class SetLevelRequestParams(RequestParams):
    """Parameters for setting the logging level."""

    level: LoggingLevel
    """The level of logging that the client wants to receive from the server."""
    model_config = ConfigDict(extra="allow")


class SetLevelRequest(Request[SetLevelRequestParams, Literal["logging/setLevel"]]):
    """A request from the client to the server, to enable or adjust logging."""

    method: Literal["logging/setLevel"] = "logging/setLevel"
    params: SetLevelRequestParams


class LoggingMessageNotificationParams(NotificationParams):
    """Parameters for logging message notifications."""

    level: LoggingLevel
    """The severity of this log message."""
    logger: str | None = None
    """An optional name of the logger issuing this message."""
    data: Any
    """
    The data to be logged, such as a string message or an object. Any JSON serializable
    type is allowed here.
    """
    model_config = ConfigDict(extra="allow")


class LoggingMessageNotification(Notification[LoggingMessageNotificationParams, Literal["notifications/message"]]):
    """Notification of a log message passed from server to client."""

    method: Literal["notifications/message"] = "notifications/message"
    params: LoggingMessageNotificationParams


IncludeContext = Literal["none", "thisServer", "allServers"]


class ModelHint(BaseModel):
    """Hints to use for model selection."""

    name: str | None = None
    """A hint for a model name."""

    model_config = ConfigDict(extra="allow")


class ModelPreferences(BaseModel):
    """
    The server's preferences for model selection, requested by the client during
    sampling.

    Because LLMs can vary along multiple dimensions, choosing the "best" model is
    rarely straightforward.  Different models excel in different areas—some are
    faster but less capable, others are more capable but more expensive, and so
    on. This interface allows servers to express their priorities across multiple
    dimensions to help clients make an appropriate selection for their use case.

    These preferences are always advisory. The client MAY ignore them. It is also
    up to the client to decide how to interpret these preferences and how to
    balance them against other considerations.
    """

    hints: list[ModelHint] | None = None
    """
    Optional hints to use for model selection.

    If multiple hints are specified, the client MUST evaluate them in order
    (such that the first match is taken).

    The client SHOULD prioritize these hints over the numeric priorities, but
    MAY still use the priorities to select from ambiguous matches.
    """

    costPriority: float | None = None
    """
    How much to prioritize cost when selecting a model. A value of 0 means cost
    is not important, while a value of 1 means cost is the most important
    factor.
    """

    speedPriority: float | None = None
    """
    How much to prioritize sampling speed (latency) when selecting a model. A
    value of 0 means speed is not important, while a value of 1 means speed is
    the most important factor.
    """

    intelligencePriority: float | None = None
    """
    How much to prioritize intelligence and capabilities when selecting a
    model. A value of 0 means intelligence is not important, while a value of 1
    means intelligence is the most important factor.
    """

    model_config = ConfigDict(extra="allow")


class ToolChoice(BaseModel):
    """
    Controls tool usage behavior during sampling.

    Allows the server to specify whether and how the LLM should use tools
    in its response.
    """

    mode: Literal["auto", "required", "none"] | None = None
    """
    Controls when tools are used:
    - "auto": Model decides whether to use tools (default)
    - "required": Model MUST use at least one tool before completing
    - "none": Model should not use tools
    """

    model_config = ConfigDict(extra="allow")


class CreateMessageRequestParams(RequestParams):
    """Parameters for creating a message."""

    messages: list[SamplingMessage]
    modelPreferences: ModelPreferences | None = None
    """
    The server's preferences for which model to select. The client MAY ignore
    these preferences.
    """
    systemPrompt: str | None = None
    """An optional system prompt the server wants to use for sampling."""
    includeContext: IncludeContext | None = None
    """
    A request to include context from one or more MCP servers (including the caller), to
    be attached to the prompt.
    """
    temperature: float | None = None
    maxTokens: int
    """The maximum number of tokens to sample, as requested by the server."""
    stopSequences: list[str] | None = None
    metadata: dict[str, Any] | None = None
    """Optional metadata to pass through to the LLM provider."""
    tools: list["Tool"] | None = None
    """
    Tool definitions for the LLM to use during sampling.
    Requires clientCapabilities.sampling.tools to be present.
    """
    toolChoice: ToolChoice | None = None
    """
    Controls tool usage behavior.
    Requires clientCapabilities.sampling.tools and the tools parameter to be present.
    """
    model_config = ConfigDict(extra="allow")


class CreateMessageRequest(Request[CreateMessageRequestParams, Literal["sampling/createMessage"]]):
    """A request from the server to sample an LLM via the client."""

    method: Literal["sampling/createMessage"] = "sampling/createMessage"
    params: CreateMessageRequestParams


StopReason = Literal["endTurn", "stopSequence", "maxTokens", "toolUse"] | str


class CreateMessageResult(Result):
    """The client's response to a sampling/create_message request from the server.

    This is the backwards-compatible version that returns single content (no arrays).
    Used when the request does not include tools.
    """

    role: Role
    """The role of the message sender (typically 'assistant' for LLM responses)."""
    content: SamplingContent
    """Response content. Single content block (text, image, or audio)."""
    model: str
    """The name of the model that generated the message."""
    stopReason: StopReason | None = None
    """The reason why sampling stopped, if known."""


class CreateMessageResultWithTools(Result):
    """The client's response to a sampling/create_message request when tools were provided.

    This version supports array content for tool use flows.
    """

    role: Role
    """The role of the message sender (typically 'assistant' for LLM responses)."""
    content: SamplingMessageContentBlock | list[SamplingMessageContentBlock]
    """
    Response content. May be a single content block or an array.
    May include ToolUseContent if stopReason is 'toolUse'.
    """
    model: str
    """The name of the model that generated the message."""
    stopReason: StopReason | None = None
    """
    The reason why sampling stopped, if known.
    'toolUse' indicates the model wants to use a tool.
    """

    @property
    def content_as_list(self) -> list[SamplingMessageContentBlock]:
        """Returns the content as a list of content blocks, regardless of whether
        it was originally a single block or a list."""
        return self.content if isinstance(self.content, list) else [self.content]


class ResourceTemplateReference(BaseModel):
    """A reference to a resource or resource template definition."""

    type: Literal["ref/resource"]
    uri: str
    """The URI or URI template of the resource."""
    model_config = ConfigDict(extra="allow")


@deprecated("`ResourceReference` is deprecated, you should use `ResourceTemplateReference`.")
class ResourceReference(ResourceTemplateReference):
    pass


class PromptReference(BaseModel):
    """Identifies a prompt."""

    type: Literal["ref/prompt"]
    name: str
    """The name of the prompt or prompt template"""
    model_config = ConfigDict(extra="allow")


class CompletionArgument(BaseModel):
    """The argument's information for completion requests."""

    name: str
    """The name of the argument"""
    value: str
    """The value of the argument to use for completion matching."""
    model_config = ConfigDict(extra="allow")


class CompletionContext(BaseModel):
    """Additional, optional context for completions."""

    arguments: dict[str, str] | None = None
    """Previously-resolved variables in a URI template or prompt."""
    model_config = ConfigDict(extra="allow")


class CompleteRequestParams(RequestParams):
    """Parameters for completion requests."""

    ref: ResourceTemplateReference | PromptReference
    argument: CompletionArgument
    context: CompletionContext | None = None
    """Additional, optional context for completions"""
    model_config = ConfigDict(extra="allow")


class CompleteRequest(Request[CompleteRequestParams, Literal["completion/complete"]]):
    """A request from the client to the server, to ask for completion options."""

    method: Literal["completion/complete"] = "completion/complete"
    params: CompleteRequestParams


class Completion(BaseModel):
    """Completion information."""

    values: list[str]
    """An array of completion values. Must not exceed 100 items."""
    total: int | None = None
    """
    The total number of completion options available. This can exceed the number of
    values actually sent in the response.
    """
    hasMore: bool | None = None
    """
    Indicates whether there are additional completion options beyond those provided in
    the current response, even if the exact total is unknown.
    """
    model_config = ConfigDict(extra="allow")


class CompleteResult(Result):
    """The server's response to a completion/complete request"""

    completion: Completion


class ListRootsRequest(Request[RequestParams | None, Literal["roots/list"]]):
    """
    Sent from the server to request a list of root URIs from the client. Roots allow
    servers to ask for specific directories or files to operate on. A common example
    for roots is providing a set of repositories or directories a server should operate
    on.

    This request is typically used when the server needs to understand the file system
    structure or access specific locations that the client has permission to read from.
    """

    method: Literal["roots/list"] = "roots/list"
    params: RequestParams | None = None


class Root(BaseModel):
    """Represents a root directory or file that the server can operate on."""

    uri: FileUrl
    """
    The URI identifying the root. This *must* start with file:// for now.
    This restriction may be relaxed in future versions of the protocol to allow
    other URI schemes.
    """
    name: str | None = None
    """
    An optional name for the root. This can be used to provide a human-readable
    identifier for the root, which may be useful for display purposes or for
    referencing the root in other parts of the application.
    """
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)
    """
    See [MCP specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/47339c03c143bb4ec01a26e721a1b8fe66634ebe/docs/specification/draft/basic/index.mdx#general-fields)
    for notes on _meta usage.
    """
    model_config = ConfigDict(extra="allow")


class ListRootsResult(Result):
    """
    The client's response to a roots/list request from the server.
    This result contains an array of Root objects, each representing a root directory
    or file that the server can operate on.
    """

    roots: list[Root]


class RootsListChangedNotification(
    Notification[NotificationParams | None, Literal["notifications/roots/list_changed"]]
):
    """
    A notification from the client to the server, informing it that the list of
    roots has changed.

    This notification should be sent whenever the client adds, removes, or
    modifies any root. The server should then request an updated list of roots
    using the ListRootsRequest.
    """

    method: Literal["notifications/roots/list_changed"] = "notifications/roots/list_changed"
    params: NotificationParams | None = None


class CancelledNotificationParams(NotificationParams):
    """Parameters for cancellation notifications."""

    requestId: RequestId | None = None
    """
    The ID of the request to cancel.

    This MUST correspond to the ID of a request previously issued in the same direction.
    This MUST be provided for cancelling non-task requests.
    This MUST NOT be used for cancelling tasks (use the `tasks/cancel` request instead).
    """
    reason: str | None = None
    """An optional string describing the reason for the cancellation."""

    model_config = ConfigDict(extra="allow")


class CancelledNotification(Notification[CancelledNotificationParams, Literal["notifications/cancelled"]]):
    """
    This notification can be sent by either side to indicate that it is canceling a
    previously-issued request.
    """

    method: Literal["notifications/cancelled"] = "notifications/cancelled"
    params: CancelledNotificationParams


class ElicitCompleteNotificationParams(NotificationParams):
    """Parameters for elicitation completion notifications."""

    elicitationId: str
    """The unique identifier of the elicitation that was completed."""

    model_config = ConfigDict(extra="allow")


class ElicitCompleteNotification(
    Notification[ElicitCompleteNotificationParams, Literal["notifications/elicitation/complete"]]
):
    """
    A notification from the server to the client, informing it that a URL mode
    elicitation has been completed.

    Clients MAY use the notification to automatically retry requests that received a
    URLElicitationRequiredError, update the user interface, or otherwise continue
    an interaction. However, because delivery of the notification is not guaranteed,
    clients must not wait indefinitely for a notification from the server.
    """

    method: Literal["notifications/elicitation/complete"] = "notifications/elicitation/complete"
    params: ElicitCompleteNotificationParams


ClientRequestType: TypeAlias = (
    PingRequest
    | InitializeRequest
    | CompleteRequest
    | SetLevelRequest
    | GetPromptRequest
    | ListPromptsRequest
    | ListResourcesRequest
    | ListResourceTemplatesRequest
    | ReadResourceRequest
    | SubscribeRequest
    | UnsubscribeRequest
    | CallToolRequest
    | ListToolsRequest
    | GetTaskRequest
    | GetTaskPayloadRequest
    | ListTasksRequest
    | CancelTaskRequest
)


class ClientRequest(RootModel[ClientRequestType]):
    pass


ClientNotificationType: TypeAlias = (
    CancelledNotification
    | ProgressNotification
    | InitializedNotification
    | RootsListChangedNotification
    | TaskStatusNotification
)


class ClientNotification(RootModel[ClientNotificationType]):
    pass


# Type for elicitation schema - a JSON Schema dict
ElicitRequestedSchema: TypeAlias = dict[str, Any]
"""Schema for elicitation requests."""


class ElicitRequestFormParams(RequestParams):
    """Parameters for form mode elicitation requests.

    Form mode collects non-sensitive information from the user via an in-band form
    rendered by the client.
    """

    mode: Literal["form"] = "form"
    """The elicitation mode (always "form" for this type)."""

    message: str
    """The message to present to the user describing what information is being requested."""

    requestedSchema: ElicitRequestedSchema
    """
    A restricted subset of JSON Schema defining the structure of expected response.
    Only top-level properties are allowed, without nesting.
    """

    model_config = ConfigDict(extra="allow")


class ElicitRequestURLParams(RequestParams):
    """Parameters for URL mode elicitation requests.

    URL mode directs users to external URLs for sensitive out-of-band interactions
    like OAuth flows, credential collection, or payment processing.
    """

    mode: Literal["url"] = "url"
    """The elicitation mode (always "url" for this type)."""

    message: str
    """The message to present to the user explaining why the interaction is needed."""

    url: str
    """The URL that the user should navigate to."""

    elicitationId: str
    """
    The ID of the elicitation, which must be unique within the context of the server.
    The client MUST treat this ID as an opaque value.
    """

    model_config = ConfigDict(extra="allow")


# Union type for elicitation request parameters
ElicitRequestParams: TypeAlias = ElicitRequestURLParams | ElicitRequestFormParams
"""Parameters for elicitation requests - either form or URL mode."""


class ElicitRequest(Request[ElicitRequestParams, Literal["elicitation/create"]]):
    """A request from the server to elicit information from the client."""

    method: Literal["elicitation/create"] = "elicitation/create"
    params: ElicitRequestParams


class ElicitResult(Result):
    """The client's response to an elicitation request."""

    action: Literal["accept", "decline", "cancel"]
    """
    The user action in response to the elicitation.
    - "accept": User submitted the form/confirmed the action (or consented to URL navigation)
    - "decline": User explicitly declined the action
    - "cancel": User dismissed without making an explicit choice
    """

    content: dict[str, str | int | float | bool | list[str] | None] | None = None
    """
    The submitted form data, only present when action is "accept" in form mode.
    Contains values matching the requested schema. Values can be strings, integers,
    booleans, or arrays of strings.
    For URL mode, this field is omitted.
    """


class ElicitationRequiredErrorData(BaseModel):
    """Error data for URLElicitationRequiredError.

    Servers return this when a request cannot be processed until one or more
    URL mode elicitations are completed.
    """

    elicitations: list[ElicitRequestURLParams]
    """List of URL mode elicitations that must be completed."""

    model_config = ConfigDict(extra="allow")


ClientResultType: TypeAlias = (
    EmptyResult
    | CreateMessageResult
    | CreateMessageResultWithTools
    | ListRootsResult
    | ElicitResult
    | GetTaskResult
    | GetTaskPayloadResult
    | ListTasksResult
    | CancelTaskResult
    | CreateTaskResult
)


class ClientResult(RootModel[ClientResultType]):
    pass


ServerRequestType: TypeAlias = (
    PingRequest
    | CreateMessageRequest
    | ListRootsRequest
    | ElicitRequest
    | GetTaskRequest
    | GetTaskPayloadRequest
    | ListTasksRequest
    | CancelTaskRequest
)


class ServerRequest(RootModel[ServerRequestType]):
    pass


ServerNotificationType: TypeAlias = (
    CancelledNotification
    | ProgressNotification
    | LoggingMessageNotification
    | ResourceUpdatedNotification
    | ResourceListChangedNotification
    | ToolListChangedNotification
    | PromptListChangedNotification
    | ElicitCompleteNotification
    | TaskStatusNotification
)


class ServerNotification(RootModel[ServerNotificationType]):
    pass


ServerResultType: TypeAlias = (
    EmptyResult
    | InitializeResult
    | CompleteResult
    | GetPromptResult
    | ListPromptsResult
    | ListResourcesResult
    | ListResourceTemplatesResult
    | ReadResourceResult
    | CallToolResult
    | ListToolsResult
    | GetTaskResult
    | GetTaskPayloadResult
    | ListTasksResult
    | CancelTaskResult
    | CreateTaskResult
)


class ServerResult(RootModel[ServerResultType]):
    pass
