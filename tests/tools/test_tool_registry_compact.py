"""Tests for ToolRegistry compact schema support (Stage 2C)."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import _COMPACT_ENUM_THRESHOLD, ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_schema(
    name: str = "my_tool",
    description: str = "A tool",
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal OpenAI function schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": [],
            },
        },
    }


class _SimpleTool(Tool):
    """Minimal tool that returns a fixed schema."""

    def __init__(self, name: str, schema: dict[str, Any]):
        self._name = name
        self._schema = schema

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._schema["function"]["description"]

    @property
    def parameters(self) -> dict[str, Any]:
        return self._schema["function"]["parameters"]

    async def execute(self, **kwargs: Any) -> Any:
        return "ok"

    def to_schema(self) -> dict[str, Any]:
        return self._schema


# ---------------------------------------------------------------------------
# compact_schemas disabled (default) — schemas pass through unchanged
# ---------------------------------------------------------------------------


def test_compact_disabled_by_default_schemas_unchanged():
    registry = ToolRegistry()  # compact_schemas=False by default
    props = {"path": {"type": "string", "description": "The file path", "default": "/tmp"}}
    tool = _SimpleTool("read_file", _make_schema("read_file", "Read a file", props))
    registry.register(tool)

    defs = registry.get_definitions()
    param = defs[0]["function"]["parameters"]["properties"]["path"]

    assert param.get("description") == "The file path"
    assert param.get("default") == "/tmp"


# ---------------------------------------------------------------------------
# compact_schemas enabled — parameter descriptions stripped
# ---------------------------------------------------------------------------


def test_compact_strips_parameter_descriptions():
    props = {"path": {"type": "string", "description": "The file path"}}
    schema = _make_schema("read_file", "Read a file", props)
    result = ToolRegistry._compact_schema(schema, max_desc_length=0)
    assert "description" not in result["function"]["parameters"]["properties"]["path"]


def test_compact_removes_parameter_defaults():
    props = {"encoding": {"type": "string", "default": "utf-8"}}
    schema = _make_schema("read_file", "Read a file", props)
    result = ToolRegistry._compact_schema(schema, max_desc_length=0)
    assert "default" not in result["function"]["parameters"]["properties"]["encoding"]


# ---------------------------------------------------------------------------
# Enum collapsing
# ---------------------------------------------------------------------------


def test_compact_collapses_long_enum_to_type():
    long_enum = [f"val_{i}" for i in range(_COMPACT_ENUM_THRESHOLD + 1)]
    props = {"country": {"type": "string", "enum": long_enum}}
    schema = _make_schema("search", "Search tool", props)
    result = ToolRegistry._compact_schema(schema, max_desc_length=0)
    param = result["function"]["parameters"]["properties"]["country"]
    assert "enum" not in param
    assert param["type"] == "string"


def test_compact_preserves_short_enum():
    short_enum = ["low", "medium", "high"]
    assert len(short_enum) <= _COMPACT_ENUM_THRESHOLD
    props = {"level": {"type": "string", "enum": short_enum}}
    schema = _make_schema("log", "Log tool", props)
    result = ToolRegistry._compact_schema(schema, max_desc_length=0)
    param = result["function"]["parameters"]["properties"]["level"]
    assert param.get("enum") == short_enum


def test_compact_preserves_exactly_threshold_enum():
    threshold_enum = [f"v{i}" for i in range(_COMPACT_ENUM_THRESHOLD)]
    assert len(threshold_enum) == _COMPACT_ENUM_THRESHOLD
    props = {"opt": {"type": "string", "enum": threshold_enum}}
    schema = _make_schema("tool", "A tool", props)
    result = ToolRegistry._compact_schema(schema, max_desc_length=0)
    assert result["function"]["parameters"]["properties"]["opt"].get("enum") == threshold_enum


# ---------------------------------------------------------------------------
# Top-level description truncation
# ---------------------------------------------------------------------------


def test_compact_truncates_long_top_level_description():
    long_desc = "A" * 200
    schema = _make_schema("tool", long_desc)
    result = ToolRegistry._compact_schema(schema, max_desc_length=80)
    assert result["function"]["description"] == "A" * 80


def test_compact_preserves_short_top_level_description():
    short_desc = "Short description"
    schema = _make_schema("tool", short_desc)
    result = ToolRegistry._compact_schema(schema, max_desc_length=80)
    assert result["function"]["description"] == short_desc


def test_compact_zero_max_desc_length_disables_truncation():
    long_desc = "B" * 200
    schema = _make_schema("tool", long_desc)
    result = ToolRegistry._compact_schema(schema, max_desc_length=0)
    assert result["function"]["description"] == long_desc


# ---------------------------------------------------------------------------
# Nested object properties are also stripped
# ---------------------------------------------------------------------------


def test_compact_strips_nested_object_properties():
    props = {
        "options": {
            "type": "object",
            "description": "Options object",
            "properties": {
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 30,
                }
            },
        }
    }
    schema = _make_schema("run", "Run tool", props)
    result = ToolRegistry._compact_schema(schema, max_desc_length=0)
    outer = result["function"]["parameters"]["properties"]["options"]
    inner = outer["properties"]["timeout"]
    # Nested description and default should be stripped
    assert "description" not in inner
    assert "default" not in inner
    # Outer property description also stripped
    assert "description" not in outer


# ---------------------------------------------------------------------------
# get_definitions applies compact when enabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_definitions_compact_enabled_strips_params():
    long_desc = "D" * 200
    props = {"q": {"type": "string", "description": "The query", "default": ""}}
    schema = _make_schema("search", long_desc, props)
    tool = _SimpleTool("search", schema)

    registry = ToolRegistry(compact_schemas=True, compact_schemas_max_desc_length=50)
    registry.register(tool)

    defs = registry.get_definitions()
    fn = defs[0]["function"]
    param = fn["parameters"]["properties"]["q"]

    assert len(fn["description"]) == 50
    assert "description" not in param
    assert "default" not in param


@pytest.mark.asyncio
async def test_get_definitions_compact_disabled_passes_through():
    long_desc = "E" * 200
    props = {"q": {"type": "string", "description": "The query"}}
    schema = _make_schema("search", long_desc, props)
    tool = _SimpleTool("search", schema)

    registry = ToolRegistry(compact_schemas=False)
    registry.register(tool)

    defs = registry.get_definitions()
    fn = defs[0]["function"]
    assert fn["description"] == long_desc
    assert fn["parameters"]["properties"]["q"]["description"] == "The query"


# ---------------------------------------------------------------------------
# _compact_schema does not mutate the original schema
# ---------------------------------------------------------------------------


def test_compact_schema_does_not_mutate_original():
    props = {"path": {"type": "string", "description": "A path", "default": "/"}}
    original = _make_schema("tool", "A" * 200, props)
    import copy

    original_copy = copy.deepcopy(original)

    ToolRegistry._compact_schema(original, max_desc_length=10)

    assert original == original_copy
