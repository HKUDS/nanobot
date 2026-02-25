"""Resource template functionality."""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, validate_call

from mcp.server.fastmcp.resources.types import FunctionResource, Resource
from mcp.server.fastmcp.utilities.context_injection import find_context_parameter, inject_context
from mcp.server.fastmcp.utilities.func_metadata import func_metadata
from mcp.types import Annotations, Icon

if TYPE_CHECKING:
    from mcp.server.fastmcp.server import Context
    from mcp.server.session import ServerSessionT
    from mcp.shared.context import LifespanContextT, RequestT


class ResourceTemplate(BaseModel):
    """A template for dynamically creating resources."""

    uri_template: str = Field(description="URI template with parameters (e.g. weather://{city}/current)")
    name: str = Field(description="Name of the resource")
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of what the resource does")
    mime_type: str = Field(default="text/plain", description="MIME type of the resource content")
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for the resource template")
    annotations: Annotations | None = Field(default=None, description="Optional annotations for the resource template")
    meta: dict[str, Any] | None = Field(default=None, description="Optional metadata for this resource template")
    fn: Callable[..., Any] = Field(exclude=True)
    parameters: dict[str, Any] = Field(description="JSON schema for function parameters")
    context_kwarg: str | None = Field(None, description="Name of the kwarg that should receive context")

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        uri_template: str,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        icons: list[Icon] | None = None,
        annotations: Annotations | None = None,
        meta: dict[str, Any] | None = None,
        context_kwarg: str | None = None,
    ) -> ResourceTemplate:
        """Create a template from a function."""
        func_name = name or fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")  # pragma: no cover

        # Find context parameter if it exists
        if context_kwarg is None:  # pragma: no branch
            context_kwarg = find_context_parameter(fn)

        # Get schema from func_metadata, excluding context parameter
        func_arg_metadata = func_metadata(
            fn,
            skip_names=[context_kwarg] if context_kwarg is not None else [],
        )
        parameters = func_arg_metadata.arg_model.model_json_schema()

        # ensure the arguments are properly cast
        fn = validate_call(fn)

        return cls(
            uri_template=uri_template,
            name=func_name,
            title=title,
            description=description or fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            icons=icons,
            annotations=annotations,
            meta=meta,
            fn=fn,
            parameters=parameters,
            context_kwarg=context_kwarg,
        )

    def matches(self, uri: str) -> dict[str, Any] | None:
        """Check if URI matches template and extract parameters."""
        # Convert template to regex pattern
        pattern = self.uri_template.replace("{", "(?P<").replace("}", ">[^/]+)")
        match = re.match(f"^{pattern}$", uri)
        if match:
            return match.groupdict()
        return None

    async def create_resource(
        self,
        uri: str,
        params: dict[str, Any],
        context: Context[ServerSessionT, LifespanContextT, RequestT] | None = None,
    ) -> Resource:
        """Create a resource from the template with the given parameters."""
        try:
            # Add context to params if needed
            params = inject_context(self.fn, params, context, self.context_kwarg)

            # Call function and check if result is a coroutine
            result = self.fn(**params)
            if inspect.iscoroutine(result):
                result = await result

            return FunctionResource(
                uri=uri,  # type: ignore
                name=self.name,
                title=self.title,
                description=self.description,
                mime_type=self.mime_type,
                icons=self.icons,
                annotations=self.annotations,
                meta=self.meta,
                fn=lambda: result,  # Capture result in closure
            )
        except Exception as e:
            raise ValueError(f"Error creating resource from template: {e}")
