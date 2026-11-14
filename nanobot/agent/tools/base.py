from __future__ import annotations

import typing
from abc import ABC, abstractmethod
from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar, cast

if typing.TYPE_CHECKING:
    from pydantic import BaseModel

    from nanobot.agent.tools.context import ToolContext
    from nanobot.runtime_context import RuntimeContextProvider

_ToolT = TypeVar("_ToolT", bound="Tool")

class Schema(ABC):
    """Abstract base for JSON Schema fragments describing tool parameters.

    Concrete types live in :mod:`nanobot.agent.tools.schema`; all implement
    :meth:`to_json_schema` and :meth:`validate_value`. Class methods
    :meth:`validate_json_schema_value` and :meth:`fragment` are the shared validation and normalization entry points.
    """

    @staticmethod
    def validate_json_schema_value(
        val: Any, schema: dict[str, Any] | bool, path: str = "",
    ) -> list[str]:
        """Validate ``val`` against a JSON Schema fragment; returns error messages (empty means valid).

        Used by :class:`Tool` and each concrete Schema's :meth:`validate_value`.
        """
        from nanobot.agent.tools.json_schema import validate_value

        return validate_value(val, schema, path)

    @staticmethod
    def fragment(value: Any) -> dict[str, Any]:
        """Normalize a Schema instance or an existing JSON Schema dict to a fragment dict."""
        # Try to_json_schema first: Schema instances must be distinguished from dicts that are already JSON Schema
        to_js = getattr(value, "to_json_schema", None)
        if callable(to_js):
            return cast(dict[str, Any], to_js())
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
        raise TypeError(f"Expected schema object or dict, got {type(value).__name__}")

    @abstractmethod
    def to_json_schema(self) -> dict[str, Any]:
        """Return a fragment dict compatible with :meth:`validate_json_schema_value`."""
        ...

    def validate_value(self, value: Any, path: str = "") -> list[str]:
        """Validate a single value; returns error messages (empty means pass). Subclasses may override for extra rules."""
        return Schema.validate_json_schema_value(value, self.to_json_schema(), path)


class ToolResult(str):
    """String-compatible tool output with structured status."""

    is_error: bool
    error_code: str | None

    def __new__(cls, content: str, *, is_error: bool = False, error_code: str | None = None) -> ToolResult:
        obj = str.__new__(cls, content)
        obj.is_error = is_error
        obj.error_code = error_code
        return obj

    @classmethod
    def error(cls, content: str, *, error_code: str | None = None) -> ToolResult:
        return cls(content, is_error=True, error_code=error_code)


class Tool(ABC):
    """Agent capability: read files, run commands, etc."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used in function calls."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        ...

    @property
    def read_only(self) -> bool:
        """Whether this tool is side-effect free and safe to parallelize."""
        return False

    @property
    def concurrency_safe(self) -> bool:
        """Whether this tool can run alongside other concurrency-safe tools."""
        return self.read_only and not self.exclusive

    @property
    def exclusive(self) -> bool:
        """Whether this tool should run alone even if concurrency is enabled."""
        return False


    config_key: str = ""
    _plugin_discoverable: bool = True
    _scopes: set[str] = {"core"}

    @classmethod
    def config_cls(cls) -> type[BaseModel] | None:
        return None

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return True

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    def runtime_context_provider(self) -> RuntimeContextProvider | None:
        """Return optional per-turn prompt context owned by this tool."""
        return None

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Run the tool; return content, or ``ToolResult.error(...)`` for failures."""
        ...

    @staticmethod
    def error(content: str) -> ToolResult:
        return ToolResult.error(content)

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate against JSON schema; empty list means valid."""
        if not isinstance(cast(object, params), dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return Schema.validate_json_schema_value(params, {**schema, "type": "object"}, "")

    def to_schema(self) -> dict[str, Any]:
        """OpenAI function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def tool_parameters(schema: dict[str, Any]) -> Callable[[type[_ToolT]], type[_ToolT]]:
    """Class decorator: attach JSON Schema and inject a concrete ``parameters`` property.

    Use on ``Tool`` subclasses instead of writing ``@property def parameters``. The
    schema is stored on the class and returned as a fresh copy on each access.

    Example::

        @tool_parameters({
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        })
        class ReadFileTool(Tool):
            ...
    """

    def decorator(cls: type[_ToolT]) -> type[_ToolT]:
        frozen = deepcopy(schema)

        @property
        def parameters(self: Any) -> dict[str, Any]:
            return deepcopy(frozen)

        cls.parameters = parameters  # type: ignore[assignment]

        abstract = getattr(cls, "__abstractmethods__", None)
        if abstract is not None and "parameters" in abstract:
            cls.__abstractmethods__ = frozenset(abstract - {"parameters"})  # type: ignore[misc]

        return cls

    return decorator
