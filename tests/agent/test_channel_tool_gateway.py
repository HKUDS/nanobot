"""Tests for the guarded tool gateway exposed to opt-in channel plugins."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import current_request_context
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema
from nanobot.security.workspace_access import current_workspace_scope


class _ContextProbeTool(Tool):
    @property
    def name(self) -> str:
        return "context_probe"

    @property
    def description(self) -> str:
        return "Expose the runtime context for a regression test."

    @property
    def parameters(self) -> dict:
        return tool_parameters_schema(value=StringSchema("Value to echo"), required=["value"])

    async def execute(self, value: str) -> dict:
        request = current_request_context()
        scope = current_workspace_scope()
        assert request is not None
        assert scope is not None
        return {
            "value": value,
            "channel": request.channel,
            "chat_id": request.chat_id,
            "session_key": request.session_key,
            "workspace": str(request.workspace),
            "scope_workspace": str(scope.project_path),
        }


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation = SimpleNamespace(
        max_tokens=4096,
        temperature=0.1,
        reasoning_effort=None,
    )
    return provider


@pytest.mark.asyncio
async def test_channel_tool_gateway_binds_turn_context_and_resets_it(tmp_path, loop_factory):
    loop = loop_factory(provider=_provider())
    loop.tools.register(_ContextProbeTool())

    result = await loop.execute_tool(
        "websocket:chat-1",
        "context_probe",
        {"value": "ok"},
        channel="websocket",
        chat_id="chat-1",
    )

    assert result == {
        "value": "ok",
        "channel": "websocket",
        "chat_id": "chat-1",
        "session_key": "websocket:chat-1",
        "workspace": str(tmp_path),
        "scope_workspace": str(tmp_path),
    }
    assert current_request_context() is None
    assert current_workspace_scope() is None


@pytest.mark.asyncio
async def test_channel_tool_gateway_uses_registry_validation(loop_factory):
    loop = loop_factory(provider=_provider())
    loop.tools.register(_ContextProbeTool())

    result = await loop.execute_tool(
        "cli:direct",
        "context_probe",
        {},
        channel="cli",
        chat_id="direct",
    )

    assert result.is_error
    assert "missing required value" in result
