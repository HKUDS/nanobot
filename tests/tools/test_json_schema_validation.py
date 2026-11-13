"""Tool calls use the server's schema, reject invalid arguments, and allow correction."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.mcp import MCPToolWrapper
from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result


@tool_parameters({
    "type": "object",
    "properties": {"count": {"type": "integer"}},
    "required": ["count"],
})
class CountingTool(Tool):
    name = "counting"
    description = "Count without changing the supplied value."

    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return "ok"


async def test_model_can_correct_type_error_and_retry():
    tool = CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    arguments = {"count": "123"}

    result = await registry.execute(tool.name, arguments)

    assert is_tool_error_result(result)
    assert "count: '123' is not of type 'integer'" in result
    assert arguments == {"count": "123"}
    assert tool.calls == []
    assert await registry.execute(tool.name, {"count": 123}) == "ok"
    assert tool.calls == [{"count": 123}]


def make_mcp_registry(schema):
    session = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(content=[])))
    wrapper = MCPToolWrapper(session, "schema", SimpleNamespace(
        name="check", description="Check arguments", inputSchema=schema,
    ))
    registry = ToolRegistry()
    registry.register(wrapper)
    return registry, wrapper, session


ADDRESS_SCHEMA = {
    "type": "object",
    "$defs": {
        "Address/model": {
            "type": "object",
            "properties": {"city": {"type": "string"}, "zip": {"type": "integer"}},
            "required": ["city", "zip"],
        },
    },
    "properties": {
        "addr": {"$ref": "#/$defs/Address~1model"},
        "count": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
    },
    "required": ["addr"],
}


@pytest.mark.parametrize("arguments, expected", [
    ({"addr": {"zip": "98101"}}, ["addr:", "city", "addr.zip:", "integer"]),
    ({"addr": "Seattle"}, ["addr:", "object"]),
    ({"addr": '{"city":"Seattle","zip":98101}'}, ["addr:", "object"]),
    ({"addr": {"city": "Seattle", "zip": 98101}, "count": {}}, ["count:", "integer", "string"]),
])
async def test_mcp_ref_and_union_errors_reach_model(arguments, expected):
    registry, wrapper, session = make_mcp_registry(deepcopy(ADDRESS_SCHEMA))

    result = await registry.execute(wrapper.name, arguments)

    assert is_tool_error_result(result)
    for text in expected:
        assert text in result
    session.call_tool.assert_not_awaited()


@pytest.mark.parametrize("count", [3, "three"])
def test_mcp_ref_and_union_accept_valid_arguments(count):
    registry, wrapper, _ = make_mcp_registry(deepcopy(ADDRESS_SCHEMA))
    arguments = {"addr": {"city": "Seattle", "zip": 98101}, "count": count}

    _, prepared, error = registry.prepare_call(wrapper.name, arguments)

    assert error is None
    assert prepared == arguments


def test_mcp_nullable_model_validates_original_schema():
    schema = deepcopy(ADDRESS_SCHEMA)
    schema["properties"]["addr"] = {
        "anyOf": [{"$ref": "#/$defs/Address~1model"}, {"type": "null"}],
        "default": None,
    }
    original = deepcopy(schema)
    registry, wrapper, _ = make_mcp_registry(schema)

    assert wrapper.parameters["properties"]["addr"]["nullable"] is True
    assert registry.prepare_call(wrapper.name, {"addr": None})[2] is None
    assert schema == original


@pytest.mark.parametrize("parent", [
    {"type": "page_id", "page_id": "synthetic-page"},
    {"type": "database_id", "database_id": "synthetic-database"},
    {"type": "workspace"},
])
def test_notion_style_parent_discriminator_accepts_one_branch(parent):
    # Same oneOf/const structure as @notionhq/notion-mcp-server's move-page parent.
    schema = {
        "type": "object",
        "properties": {"parent": {"$ref": "#/$defs/parent"}},
        "$defs": {"parent": {"oneOf": [
            {"type": "object", "properties": {"type": {"const": "page_id"}, "page_id": {"type": "string"}}, "required": ["type", "page_id"]},
            {"type": "object", "properties": {"type": {"const": "database_id"}, "database_id": {"type": "string"}}, "required": ["type", "database_id"]},
            {"type": "object", "properties": {"type": {"const": "workspace"}}, "required": ["type"]},
        ]}},
    }
    registry, wrapper, _ = make_mcp_registry(schema)

    assert registry.prepare_call(wrapper.name, {"parent": parent})[2] is None
    error = registry.prepare_call(wrapper.name, {"parent": {**parent, "type": "invalid"}})[2]
    assert is_tool_error_result(error)
    assert "parent.type:" in error


@pytest.mark.parametrize("dialect, array_schema", [
    ("http://json-schema.org/draft-07/schema#", {
        "type": "array", "items": [{"type": "string"}, {"type": "integer"}],
        "additionalItems": False,
    }),
    ("https://json-schema.org/draft/2020-12/schema", {
        "type": "array", "prefixItems": [{"type": "string"}, {"type": "integer"}],
        "items": False,
    }),
])
def test_positional_array_schemas_validate_without_casting(dialect, array_schema):
    registry, wrapper, _ = make_mcp_registry({
        "$schema": dialect, "type": "object", "properties": {"pair": array_schema},
    })

    assert registry.prepare_call(wrapper.name, {"pair": ["a", 1]})[2] is None
    error = registry.prepare_call(wrapper.name, {"pair": ["a", "1"]})[2]
    assert is_tool_error_result(error)
    assert "pair[1]: '1' is not of type 'integer'" in error
    assert is_tool_error_result(registry.prepare_call(wrapper.name, {"pair": ["a", 1, 2]})[2])


def test_malformed_server_schema_returns_tool_error():
    registry, wrapper, _ = make_mcp_registry({
        "type": "object", "properties": {"pair": {"type": "array", "items": []}},
    })

    error = registry.prepare_call(wrapper.name, {"pair": [1]})[2]

    assert is_tool_error_result(error)
    assert "Invalid tool schema" in error


@pytest.mark.parametrize("reference", ["https://example.invalid/schema", "file:///private/schema.json"])
def test_server_schema_cannot_load_external_references(monkeypatch, reference):
    retrieve = Mock(side_effect=AssertionError("Schema validation must not perform I/O"))
    monkeypatch.setattr("urllib.request.urlopen", retrieve)
    registry, wrapper, _ = make_mcp_registry({
        "type": "object", "properties": {"value": {"$ref": reference}},
    })

    error = registry.prepare_call(wrapper.name, {"value": 1})[2]

    assert is_tool_error_result(error)
    assert "resolve" in error.lower()
    retrieve.assert_not_called()


@pytest.mark.parametrize("dialect", [
    "https://example.invalid/unsupported-dialect", {}, [], None,
])
async def test_invalid_declared_dialect_returns_error_without_calling_server(dialect):
    registry, wrapper, session = make_mcp_registry({
        "$schema": dialect, "type": "object", "properties": {},
    })

    result = await registry.execute(wrapper.name, {})

    assert is_tool_error_result(result)
    assert "Invalid tool schema" in result
    assert ("Unsupported JSON Schema dialect" if isinstance(dialect, str) else "$schema must be a string") in result
    session.call_tool.assert_not_awaited()


@pytest.mark.parametrize("amount, valid", [
    (4.02, True), (4.021, False), (-4.02, True), (0.07000000000000002, False),
])
async def test_decimal_multiple_of_does_not_use_binary_rounding_or_tolerance(amount, valid):
    registry, wrapper, session = make_mcp_registry({
        "type": "object", "properties": {"amount": {"type": "number", "multipleOf": 0.01}},
    })
    arguments = {"amount": amount}

    result = await registry.execute(wrapper.name, arguments)

    assert is_tool_error_result(result) is not valid
    assert arguments == {"amount": amount}
    assert session.call_tool.await_count == int(valid)
    if not valid:
        assert "amount:" in result and "multiple" in result


@pytest.mark.parametrize("dialect", [None, "http://json-schema.org/draft-07/schema#"])
@pytest.mark.parametrize("expression, name, valid", [
    (r"^\p{L}+$", "北京", True),
    (r"^\p{L}+$", "123", False),
    ("[", "北京", False),
])
async def test_string_pattern_uses_unicode_engine_and_rejects_invalid_schema(dialect, expression, name, valid):
    schema = {"type": "object", "properties": {"name": {"type": "string", "pattern": expression}}}
    if dialect is not None:
        schema["$schema"] = dialect
    registry, wrapper, session = make_mcp_registry(schema)

    result = await registry.execute(wrapper.name, {"name": name})

    assert is_tool_error_result(result) is not valid
    assert session.call_tool.await_count == int(valid)
    if not valid:
        assert ("Invalid tool schema" if expression == "[" else "name:") in result
