from __future__ import annotations

from typing import Any

from blackcat.agent.tools.base import Tool
from blackcat.agent.tools.filesystem import ReadFileTool
from blackcat.agent.tools.registry import ToolRegistry


class _FakeTool(Tool):
    def __init__(self, name: str, schema: dict[str, Any] | None = None):
        self._name = name
        self._schema = schema

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return self._schema or {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> Any:
        return kwargs


def _tool_names(definitions: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for definition in definitions:
        fn = definition.get("function", {})
        names.append(fn.get("name", ""))
    return names


def _registry_with_names(names: list[str]) -> ToolRegistry:
    registry = ToolRegistry()
    for name in names:
        registry.register(_FakeTool(name))
    return registry


def test_get_definitions_orders_builtins_then_mcp_tools() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("mcp_git_status"))
    registry.register(_FakeTool("write_file"))
    registry.register(_FakeTool("mcp_fs_list"))
    registry.register(_FakeTool("read_file"))

    assert _tool_names(registry.get_definitions()) == [
        "read_file",
        "write_file",
        "mcp_fs_list",
        "mcp_git_status",
    ]


def test_prepare_call_rejects_near_miss_tool_name_with_suggestion() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))

    tool, params, error = registry.prepare_call("readFile", {"path": "foo.txt"})

    assert tool is None
    assert params == {"path": "foo.txt"}
    assert error is not None
    assert "Tool 'readFile' not found" in error
    assert "Did you mean 'read_file'?" in error
    assert "must match exactly" in error


def test_suggest_name_handles_canonical_tool_name_variants() -> None:
    registry = _registry_with_names(["read_file"])
    expected = {
        "readFile": "read_file",
        "read-file": "read_file",
        "READ_FILE": "read_file",
        "read file": "read_file",
        "readfile": "read_file",
    }

    assert {name: registry._suggest_name(name) for name in expected} == expected


def test_suggest_name_suppresses_low_confidence_and_non_unique_matches() -> None:
    registry = _registry_with_names(["read_file", "write_file"])

    for name in ["", "foo", "read", "file", "readfil", "read_file_tool"]:
        assert registry._suggest_name(name) is None

    ambiguous = _registry_with_names(["read_file", "readFile"])
    assert ambiguous._suggest_name("readfile") is None


def test_suggest_name_updates_after_register_and_unregister() -> None:
    registry = _registry_with_names(["read_file"])

    assert registry._suggest_name("readFile") == "read_file"

    registry.register(_FakeTool("readFile"))
    assert registry._suggest_name("read-file") is None

    registry.unregister("read_file")
    assert registry._suggest_name("read-file") == "readFile"


def test_prepare_call_read_file_rejects_non_object_params_with_actionable_hint() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))

    tool, params, error = registry.prepare_call("read_file", ["foo.txt"])

    assert tool is not None
    assert params == ["foo.txt"]
    assert error is not None
    assert "must be a JSON object" in error
    assert 'tool_name(param1="value1", param2="value2")' in error
    assert "matching the tool schema" in error


def test_prepare_call_parses_json_string_arguments() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))

    tool, params, error = registry.prepare_call("read_file", '{"path":"foo.txt"}')

    assert tool is not None
    assert params == {"path": "foo.txt"}
    assert error is None


def test_prepare_call_rejects_malformed_json_string_arguments() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))

    tool, params, error = registry.prepare_call("read_file", '{path:"foo.txt"}')

    assert tool is not None
    assert params == '{path:"foo.txt"}'
    assert error is not None
    assert "parameters must be a JSON object" in error


def test_prepare_call_rejects_scalar_for_single_required_parameter() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool(
        "web_fetch",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    ))

    tool, params, error = registry.prepare_call("web_fetch", "https://example.com")

    assert tool is not None
    assert params == "https://example.com"
    assert error is not None
    assert "parameters must be a JSON object" in error


def test_prepare_call_rejects_unquoted_scalar_strings_before_schema_cast() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool(
        "message",
        {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
    ))

    tool, params, error = registry.prepare_call("message", "true")

    assert tool is not None
    assert params == "true"
    assert error is not None
    assert "parameters must be a JSON object" in error


def test_prepare_call_unwraps_arguments_payload() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool(
        "read_file",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ))

    tool, params, error = registry.prepare_call(
        "read_file",
        {"arguments": '{"path":"foo.txt"}'},
    )

    assert tool is not None
    assert params == {"path": "foo.txt"}
    assert error is None


def test_prepare_call_treats_none_arguments_as_empty_object() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("list_exec_sessions"))

    tool, params, error = registry.prepare_call("list_exec_sessions", None)

    assert tool is not None
    assert params == {}
    assert error is None

    tool, params, error = registry.prepare_call("list_exec_sessions", "null")

    assert tool is not None
    assert params == "null"
    assert error is not None
    assert "parameters must be a JSON object" in error


def test_prepare_call_other_tools_keep_generic_object_validation() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("grep"))

    tool, params, error = registry.prepare_call("grep", ["TODO"])

    assert tool is not None
    assert params == ["TODO"]
    assert error == (
        "Error: Tool 'grep' parameters must be a JSON object, got list. "
        'Use named parameters like tool_name(param1="value1", param2="value2") '
        "matching the tool schema."
    )


async def test_registry_rejects_unknown_builtin_tool_parameters(tmp_path) -> None:
    (tmp_path / "sample.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(
        ReadFileTool(
            workspace=tmp_path,
            allowed_dir=tmp_path,
            restrict_to_workspace=True,
        )
    )

    result = await registry.execute(
        "read_file",
        {"path": "sample.txt", "line_limit": 1},
    )

    assert "Invalid parameters" in result
    assert "unexpected parameter line_limit" in result
    assert "one" not in result


def test_get_definitions_returns_cached_result() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    first = registry.get_definitions()
    assert registry._cached_definitions is not None
    second = registry.get_definitions()
    assert first == second


def test_register_invalidates_cache() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    first = registry.get_definitions()
    registry.register(_FakeTool("write_file"))
    second = registry.get_definitions()
    assert first is not second
    assert len(second) == 2


def test_unregister_invalidates_cache() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    registry.register(_FakeTool("write_file"))
    first = registry.get_definitions()
    registry.unregister("write_file")
    second = registry.get_definitions()
    assert first is not second
    assert len(second) == 1
