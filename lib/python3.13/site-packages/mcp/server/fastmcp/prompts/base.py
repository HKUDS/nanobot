"""Base classes for FastMCP prompts."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal

import pydantic_core
from pydantic import BaseModel, Field, TypeAdapter, validate_call

from mcp.server.fastmcp.utilities.context_injection import find_context_parameter, inject_context
from mcp.server.fastmcp.utilities.func_metadata import func_metadata
from mcp.types import ContentBlock, Icon, TextContent

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT, RequestT


class Message(BaseModel):
    """Base class for all prompt messages."""

    role: Literal["user", "assistant"]
    content: ContentBlock

    def __init__(self, content: str | ContentBlock, **kwargs: Any):
        if isinstance(content, str):
            content = TextContent(type="text", text=content)
        super().__init__(content=content, **kwargs)


class UserMessage(Message):
    """A message from the user."""

    role: Literal["user", "assistant"] = "user"

    def __init__(self, content: str | ContentBlock, **kwargs: Any):
        super().__init__(content=content, **kwargs)


class AssistantMessage(Message):
    """A message from the assistant."""

    role: Literal["user", "assistant"] = "assistant"

    def __init__(self, content: str | ContentBlock, **kwargs: Any):
        super().__init__(content=content, **kwargs)


message_validator = TypeAdapter[UserMessage | AssistantMessage](UserMessage | AssistantMessage)

SyncPromptResult = str | Message | dict[str, Any] | Sequence[str | Message | dict[str, Any]]
PromptResult = SyncPromptResult | Awaitable[SyncPromptResult]


class PromptArgument(BaseModel):
    """An argument that can be passed to a prompt."""

    name: str = Field(description="Name of the argument")
    description: str | None = Field(None, description="Description of what the argument does")
    required: bool = Field(default=False, description="Whether the argument is required")


class Prompt(BaseModel):
    """A prompt template that can be rendered with parameters."""

    name: str = Field(description="Name of the prompt")
    title: str | None = Field(None, description="Human-readable title of the prompt")
    description: str | None = Field(None, description="Description of what the prompt does")
    arguments: list[PromptArgument] | None = Field(None, description="Arguments that can be passed to the prompt")
    fn: Callable[..., PromptResult | Awaitable[PromptResult]] = Field(exclude=True)
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for this prompt")
    context_kwarg: str | None = Field(None, description="Name of the kwarg that should receive context", exclude=True)

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., PromptResult | Awaitable[PromptResult]],
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        icons: list[Icon] | None = None,
        context_kwarg: str | None = None,
    ) -> Prompt:
        """Create a Prompt from a function.

        The function can return:
        - A string (converted to a message)
        - A Message object
        - A dict (converted to a message)
        - A sequence of any of the above
        """
        func_name = name or fn.__name__

        if func_name == "<lambda>":  # pragma: no cover
            raise ValueError("You must provide a name for lambda functions")

        # Find context parameter if it exists
        if context_kwarg is None:  # pragma: no branch
            context_kwarg = find_context_parameter(fn)

        # Get schema from func_metadata, excluding context parameter
        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        # Convert parameters to PromptArguments
        arguments: list[PromptArgument] = []
        if "properties" in parameters:  # pragma: no branch
            for param_name, param in parameters["properties"].items():
                required = param_name in parameters.get("required", [])
                arguments.append(
                    PromptArgument(
                        name=param_name,
                        description=param.get("description"),
                        required=required,
                    )
                )

        # ensure the arguments are properly cast
        fn = validate_call(fn)

        return cls(
            name=func_name,
            title=title,
            description=description or fn.__doc__ or "",
            arguments=arguments,
            fn=fn,
            icons=icons,
            context_kwarg=context_kwarg,
        )

    async def render(
        self,
        arguments: dict[str, Any] | None = None,
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
    ) -> list[Message]:
        """Render the prompt with arguments."""
        # Validate required arguments
        if self.arguments:
            required = {arg.name for arg in self.arguments if arg.required}
            provided = set(arguments or {})
            missing = required - provided
            if missing:
                raise ValueError(f"Missing required arguments: {missing}")

        try:
            # Add context to arguments if needed
            call_args = inject_context(self.fn, arguments or {}, context, self.context_kwarg)

            # Call function and check if result is a coroutine
            result = self.fn(**call_args)
            if inspect.iscoroutine(result):
                result = await result

            # Validate messages
            if not isinstance(result, list | tuple):
                result = [result]

            # Convert result to messages
            messages: list[Message] = []
            for msg in result:  # type: ignore[reportUnknownVariableType]
                try:
                    if isinstance(msg, Message):
                        messages.append(msg)
                    elif isinstance(msg, dict):
                        messages.append(message_validator.validate_python(msg))
                    elif isinstance(msg, str):
                        content = TextContent(type="text", text=msg)
                        messages.append(UserMessage(content=content))
                    else:  # pragma: no cover
                        content = pydantic_core.to_json(msg, fallback=str, indent=2).decode()
                        messages.append(Message(role="user", content=content))
                except Exception:  # pragma: no cover
                    raise ValueError(f"Could not convert prompt result to message: {msg}")

            return messages
        except Exception as e:  # pragma: no cover
            raise ValueError(f"Error rendering prompt {self.name}: {e}")
