"""Exercise vision observations through a real, isolated stdio MCP server."""

import asyncio
import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.context_governance import ContextGovernanceConfig, ContextGovernor
from nanobot.agent.tools.mcp import MCPProvider
from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result
from nanobot.config.schema import MCPServerConfig
from nanobot.providers.base import LLMProvider
from nanobot.providers.openai_responses.converters import convert_tool_output


@pytest.mark.asyncio
async def test_stdio_observation_and_lost_action_response(tmp_path, monkeypatch):
    # Neither image persistence nor the child process touches the user's data.
    monkeypatch.setattr("nanobot.utils.artifacts.get_media_dir", lambda: tmp_path / "media")
    actions = tmp_path / "actions.txt"
    config = MCPServerConfig.model_validate({
        "command": sys.executable,
        "args": [str(Path(__file__).parent / "fixtures/mcp_observation_server.py"), str(actions)],
        "imageOutput": "inline",
        "retryToolCalls": False,
        "toolTimeout": 10,
        "enabledTools": ["observe", "act_then_disconnect"],
    })
    registry = ToolRegistry()
    provider = MCPProvider({"desktop": config}, registry)
    try:
        await asyncio.wait_for(provider.connect(), timeout=20)
        assert provider.connected_server_names == {"desktop"}
        observation = await registry.execute("mcp_desktop_observe", {})
        assert [block["type"] for block in observation] == ["text", "text", "image_url", "text"]
        assert json.loads(observation[0]["text"])["structuredContent"]["elements"] == [
            {"element_token": "s123:1", "label": "AC"},
        ]
        assert observation[1]["text"] == "Synthetic window, before image"
        assert observation[3]["text"] == "After image: target 1"
        image = observation[2]
        assert Path(image["_meta"]["path"]).read_bytes() == base64.b64decode(
            image["image_url"]["url"].split(",", 1)[1]
        )

        # Follow the same normalization/provider conversion used by the runner.
        governance = ContextGovernanceConfig(
            provider=MagicMock(spec=LLMProvider), model="vision-test", tools=registry,
            workspace=tmp_path, session_key="synthetic", max_tool_result_chars=100,
        )
        normalized = ContextGovernor.normalize_tool_result(
            governance, "observe-1", "mcp_desktop_observe", observation,
        )
        request_content = convert_tool_output(normalized)
        assert request_content == [
            {"type": "input_text", "text": observation[0]["text"]},
            {"type": "input_text", "text": observation[1]["text"]},
            {"type": "input_image", "image_url": image["image_url"]["url"], "detail": "auto"},
            {"type": "input_text", "text": observation[3]["text"]},
        ]

        failure = await asyncio.wait_for(
            registry.execute("mcp_desktop_act_then_disconnect", {}), timeout=20,
        )
        assert is_tool_error_result(failure)
        assert "not replayed" in failure
        assert "Inspect the current state" in failure
        assert actions.read_text() == "action\n"

        # Reconnection remains available; the next call can observe before acting.
        refreshed = await registry.execute("mcp_desktop_observe", {})
        assert [block["type"] for block in refreshed] == ["text", "text", "image_url", "text"]
        assert actions.read_text() == "action\n"
    finally:
        await asyncio.wait_for(provider.aclose(), timeout=10)
