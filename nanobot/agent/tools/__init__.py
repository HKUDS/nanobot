"""Public tool contracts and discovery interfaces."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.agent.tools.base import Schema, Tool, ToolResult, tool_parameters
    from nanobot.agent.tools.context import ToolContext
    from nanobot.agent.tools.loader import ToolLoader
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.agent.tools.schema import (
        ArraySchema,
        BooleanSchema,
        IntegerSchema,
        NumberSchema,
        ObjectSchema,
        StringSchema,
        tool_parameters_schema,
    )


_EXPORTS = {
    "Schema": "nanobot.agent.tools.base",
    "ArraySchema": "nanobot.agent.tools.schema",
    "BooleanSchema": "nanobot.agent.tools.schema",
    "IntegerSchema": "nanobot.agent.tools.schema",
    "NumberSchema": "nanobot.agent.tools.schema",
    "ObjectSchema": "nanobot.agent.tools.schema",
    "StringSchema": "nanobot.agent.tools.schema",
    "Tool": "nanobot.agent.tools.base",
    "ToolContext": "nanobot.agent.tools.context",
    "ToolLoader": "nanobot.agent.tools.loader",
    "ToolResult": "nanobot.agent.tools.base",
    "ToolRegistry": "nanobot.agent.tools.registry",
    "tool_parameters": "nanobot.agent.tools.base",
    "tool_parameters_schema": "nanobot.agent.tools.schema",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "Schema",
    "ArraySchema",
    "BooleanSchema",
    "IntegerSchema",
    "NumberSchema",
    "ObjectSchema",
    "StringSchema",
    "Tool",
    "ToolContext",
    "ToolLoader",
    "ToolResult",
    "ToolRegistry",
    "tool_parameters",
    "tool_parameters_schema",
]
