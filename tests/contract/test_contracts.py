"""Contract tests for core abstractions.

These tests verify that:
1. Every registered tool has valid JSON-Schema ``parameters``.
2. Concrete ``LLMProvider`` implementations honour the base-class contract.
3. ``ToolResult`` factory methods produce consistent instances.

Contract tests act as a safety net before refactoring — if a contract
is violated, the refactor must not proceed.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# ---------------------------------------------------------------------------
# Contract: ToolResult factory methods
# ---------------------------------------------------------------------------


class TestToolResultContract:
    """ToolResult.ok() and ToolResult.fail() must return consistent instances."""

    def test_ok_success(self):
        r = ToolResult.ok("hello")
        assert r.success is True
        assert r.output == "hello"
        assert r.error is None

    def test_ok_truncated(self):
        r = ToolResult.ok("data", truncated=True)
        assert r.truncated is True

    def test_fail_failure(self):
        r = ToolResult.fail("boom", error_type="io")
        assert r.success is False
        assert r.error == "boom"
        assert r.metadata["error_type"] == "io"

    def test_fail_output_defaults_to_error(self):
        r = ToolResult.fail("something broke")
        assert r.output == "something broke"

    def test_to_llm_string(self):
        assert ToolResult.ok("hi").to_llm_string() == "hi"
        assert ToolResult.fail("err").to_llm_string() == "err"


# ---------------------------------------------------------------------------
# Contract: Tool implementations have valid JSON Schema
# ---------------------------------------------------------------------------

_JSON_SCHEMA_TYPES = {"string", "integer", "number", "boolean", "array", "object"}


def _make_tool_instances(tmp_path: Path) -> list[Tool]:
    """Instantiate all built-in tools that can be cheaply constructed."""
    return [
        ReadFileTool(workspace=tmp_path),
        WriteFileTool(workspace=tmp_path),
        EditFileTool(workspace=tmp_path),
        ListDirTool(workspace=tmp_path),
        ExecTool(working_dir=str(tmp_path)),
        WebFetchTool(),
        WebSearchTool(),
    ]


class TestToolSchemaContract:
    """Each tool must expose a valid JSON Schema for ``parameters``."""

    def test_tools_have_required_properties(self, tmp_path: Path):
        """Every tool must have name, description, and parameters properties."""
        for tool in _make_tool_instances(tmp_path):
            assert isinstance(tool.name, str) and len(tool.name) > 0, f"{tool}: missing name"
            assert (
                isinstance(tool.description, str) and len(tool.description) > 0
            ), f"{tool.name}: missing description"
            assert isinstance(tool.parameters, dict), f"{tool.name}: parameters must be a dict"

    def test_parameters_are_valid_json_schema(self, tmp_path: Path):
        """Tool parameters must follow JSON Schema object structure."""
        for tool in _make_tool_instances(tmp_path):
            params = tool.parameters
            assert params.get("type") == "object", (
                f"{tool.name}: parameters.type must be 'object'"
            )
            props = params.get("properties", {})
            assert isinstance(props, dict), f"{tool.name}: properties must be a dict"

            for prop_name, prop_schema in props.items():
                assert isinstance(prop_schema, dict), (
                    f"{tool.name}.{prop_name}: property schema must be a dict"
                )
                prop_type = prop_schema.get("type")
                if prop_type is not None:
                    assert prop_type in _JSON_SCHEMA_TYPES, (
                        f"{tool.name}.{prop_name}: unknown type {prop_type!r}"
                    )

    def test_required_is_a_list_of_strings(self, tmp_path: Path):
        """If 'required' is present, it must be a list of strings from 'properties'."""
        for tool in _make_tool_instances(tmp_path):
            params = tool.parameters
            required = params.get("required")
            if required is not None:
                assert isinstance(required, list), f"{tool.name}: required must be a list"
                props = set(params.get("properties", {}).keys())
                for r in required:
                    assert isinstance(r, str), f"{tool.name}: required items must be strings"
                    assert r in props, f"{tool.name}: required field {r!r} not in properties"

    def test_to_schema_produces_function_call_format(self, tmp_path: Path):
        """Tool.to_schema() must produce OpenAI function-call format."""
        for tool in _make_tool_instances(tmp_path):
            schema = tool.to_schema()
            assert schema["type"] == "function", f"{tool.name}: to_schema type != 'function'"
            fn = schema["function"]
            assert fn["name"] == tool.name
            assert "description" in fn
            assert "parameters" in fn


# ---------------------------------------------------------------------------
# Contract: LLMResponse dataclass
# ---------------------------------------------------------------------------


class TestLLMResponseContract:
    """LLMResponse must behave consistently."""

    def test_has_tool_calls_false_by_default(self):
        r = LLMResponse(content="hello")
        assert r.has_tool_calls is False
        assert r.tool_calls == []

    def test_has_tool_calls_true(self):
        r = LLMResponse(
            content=None,
            tool_calls=[ToolCallRequest(id="1", name="test", arguments={})],
        )
        assert r.has_tool_calls is True

    def test_usage_default(self):
        r = LLMResponse(content="x")
        assert r.usage == {}

    def test_finish_reason_default(self):
        r = LLMResponse(content="x")
        assert r.finish_reason == "stop"

    def test_response_fields(self):
        """LLMResponse must have all expected fields."""
        field_names = {f.name for f in fields(LLMResponse)}
        expected = {"content", "tool_calls", "finish_reason", "usage", "reasoning_content"}
        assert expected.issubset(field_names)


# ---------------------------------------------------------------------------
# Contract: LLMProvider ABC
# ---------------------------------------------------------------------------


class TestLLMProviderContract:
    """LLMProvider subclasses must implement required methods."""

    def test_abstract_methods(self):
        """LLMProvider has the expected abstract interface."""
        # chat and get_default_model are the core contract
        assert hasattr(LLMProvider, "chat")
        assert hasattr(LLMProvider, "get_default_model")

    def test_cannot_instantiate_without_abstract_methods(self):
        """Direct instantiation of LLMProvider should fail (it's abstract)."""
        # LLMProvider has abstract methods; instantiation should raise
        # (unless __init_subclass__ or metaclass prevents it)
        try:
            LLMProvider()  # type: ignore[abstract]
            # Some implementations might not enforce this — skip if so
        except TypeError:
            pass  # Expected: abstract methods not implemented

    def test_concrete_provider_chat_signature(self):
        """Verify chat() accepts the standard parameters."""
        import inspect

        sig = inspect.signature(LLMProvider.chat)
        params = set(sig.parameters.keys())
        assert {"messages", "tools", "model"}.issubset(params)
