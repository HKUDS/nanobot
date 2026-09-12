"""#4864: reject truncated JSON tool args and circuit-break retry loops."""

import pytest

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.registry import ToolRegistry


class _Echo(Tool):
    name = "update_goal"
    description = "goal"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "recap": {"type": "string"},
        },
    }

    async def execute(self, **kwargs):
        return "ok"


@pytest.mark.asyncio
async def test_truncated_json_args_rejected():
    reg = ToolRegistry(max_consecutive_tool_failures=3)
    reg.register(_Echo())
    bad = '{"recap": "'
    out = await reg.execute("update_goal", bad)
    assert isinstance(out, ToolResult) and out.is_error
    assert "parameters must be a JSON object" in str(out)
    assert "truncated" in str(out).lower() or "invalid JSON" in str(out)


@pytest.mark.asyncio
async def test_circuit_break_after_consecutive_failures():
    reg = ToolRegistry(max_consecutive_tool_failures=3)
    reg.register(_Echo())
    bad = '{"action": "complete", "recap": '  # truncated
    for _ in range(2):
        out = await reg.execute("update_goal", bad)
        assert out.is_error
        assert "Circuit-break" not in str(out)
    out = await reg.execute("update_goal", bad)
    assert out.is_error
    assert "Circuit-break" in str(out)
    assert reg.consecutive_failure_count("update_goal") >= 3
