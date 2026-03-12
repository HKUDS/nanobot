from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.base import Tool, ToolResult


class DemoTool(Tool):
    @property
    def name(self) -> str:
        return "demo"

    @property
    def description(self) -> str:
        return "demo tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 5},
                "count": {"type": "integer", "minimum": 1, "maximum": 2},
                "meta": {
                    "type": "object",
                    "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                },
            },
            "required": ["name"],
        }

    async def execute(self, **kwargs: Any) -> str | ToolResult:
        return "ok"


def test_tool_result_helpers() -> None:
    ok = ToolResult.ok("done", truncated=True, source="unit")
    assert ok.success is True
    assert ok.truncated is True
    assert ok.metadata["source"] == "unit"
    assert ok.to_llm_string() == "done"

    fail = ToolResult.fail("boom", error_type="validation", code=400)
    assert fail.success is False
    assert fail.error == "boom"
    assert fail.metadata["error_type"] == "validation"


def test_validate_params_schema_type_error() -> None:
    class BadTool(DemoTool):
        @property
        def parameters(self) -> dict[str, Any]:
            return {"type": "string"}

    with pytest.raises(ValueError):
        BadTool().validate_params({})


def test_validate_params_max_length_and_nested_array_errors() -> None:
    tool = DemoTool()
    errors = tool.validate_params({"name": "abcdef", "count": 3, "meta": {"tags": [1]}})
    joined = " | ".join(errors)
    assert "name must be at most 5 chars" in joined
    assert "count must be <= 2" in joined
    assert "meta.tags[0] should be string" in joined


def test_to_schema_shape() -> None:
    schema = DemoTool().to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "demo"
