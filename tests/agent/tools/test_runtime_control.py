"""Contract and security regressions for the MyTool runtime boundary."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.runtime_control import (
    RUNTIME_COMMAND_KEYS,
    RUNTIME_SNAPSHOT_KEYS,
    AgentRuntimeControl,
    RuntimeControl,
)
from nanobot.agent.tools.self import MyTool, MyToolConfig
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig


def _make_loop(tmp_path: Path, *, allow_set: bool = False) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    tools_config = ToolsConfig(my=MyToolConfig(allow_set=allow_set))
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        tools_config=tools_config,
    )


def _my_tool(loop: AgentLoop) -> MyTool:
    tool = loop.tools.get("my")
    assert isinstance(tool, MyTool)
    return tool


def test_agent_loop_assembles_my_tool_with_runtime_control(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    tool = _my_tool(loop)

    assert isinstance(tool._runtime_control, RuntimeControl)
    assert isinstance(tool._runtime_control, AgentRuntimeControl)
    assert tool._runtime_control is not loop
    assert not hasattr(tool, "_runtime_state")


def test_runtime_snapshot_has_exact_allowlist_and_redacts_secrets(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.web_config.search.api_key = "search-secret"
    loop.web_config.proxy = "http://proxy-user:proxy-secret@proxy.example"
    loop.unlisted_secret = "loop-secret"

    snapshot = _my_tool(loop)._runtime_control.snapshot()
    values = snapshot.as_mapping()

    expected_snapshot_keys = frozenset({
        "model",
        "model_preset",
        "model_presets",
        "max_iterations",
        "context_window_tokens",
        "workspace",
        "provider_retry_mode",
        "max_tool_result_chars",
        "tool_names",
        "web_config",
        "exec_config",
        "subagents",
    })
    assert RUNTIME_SNAPSHOT_KEYS == expected_snapshot_keys
    assert frozenset(values) == expected_snapshot_keys
    assert RUNTIME_COMMAND_KEYS == frozenset({
        "model",
        "model_preset",
        "max_iterations",
        "context_window_tokens",
        "provider_retry_mode",
        "max_tool_result_chars",
        "workspace",
    })
    assert "provider" not in values
    assert "sessions" not in values
    assert "restrict_to_workspace" not in values
    assert "unlisted_secret" not in values
    rendered = repr(values)
    assert "search-secret" not in rendered
    assert "proxy-secret" not in rendered
    assert "loop-secret" not in rendered
    assert snapshot.web_config["proxy"] == "<configured>"


def test_runtime_snapshot_is_detached_from_mutable_config(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    control = _my_tool(loop)._runtime_control
    snapshot = control.snapshot()
    search = snapshot.web_config["search"]
    assert isinstance(search, dict)

    search["provider"] = "mutated"
    snapshot.exec_config["allow_patterns"] = ["mutated"]
    snapshot.tool_names.append("mutated")

    refreshed = control.snapshot()
    refreshed_search = refreshed.web_config["search"]
    assert isinstance(refreshed_search, dict)
    assert refreshed_search["provider"] == loop.web_config.search.provider
    assert refreshed.exec_config["allow_patterns"] == loop.exec_config.allow_patterns
    assert "mutated" not in refreshed.tool_names


@pytest.mark.asyncio
async def test_unlisted_loop_attributes_cannot_be_read_or_modified(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, allow_set=True)
    loop.unlisted_control_plane = "internal-secret"
    original_workspace_root = loop.workspace_scopes.default_workspace
    tool = _my_tool(loop)

    inspected = await tool.execute(action="check", key="unlisted_control_plane")
    modified = await tool.execute(
        action="set",
        key="unlisted_control_plane",
        value="scratch-value",
    )
    nested = await tool.execute(
        action="set",
        key="workspace_scopes.default_workspace",
        value="elsewhere",
    )

    assert "internal-secret" not in inspected
    assert "not found" in inspected
    assert modified == "Set scratchpad.unlisted_control_plane = 'scratch-value'"
    assert loop.unlisted_control_plane == "internal-secret"
    assert "Error" in nested
    assert loop.workspace_scopes.default_workspace == original_workspace_root


@pytest.mark.asyncio
async def test_default_allow_set_and_public_parameter_schema_are_unchanged(
    tmp_path: Path,
) -> None:
    loop = _make_loop(tmp_path)
    tool = _my_tool(loop)

    assert ToolsConfig().my.allow_set is False
    assert tool.parameters == {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["check", "set"],
                "description": "Action to perform",
            },
            "key": {
                "type": "string",
                "description": (
                    "Dot-path for check/set. Examples: 'max_iterations', 'workspace', "
                    "'provider_retry_mode'. Use 'request.channel', 'request.chat_id', or "
                    "'request.sender_id' for current routing metadata. Use 'model_preset' "
                    "to switch named model presets. For check without key, shows all "
                    "config values."
                ),
            },
            "value": {
                "description": (
                    "New value (for set). Type must match target (int for "
                    "max_iterations/context_window_tokens, str for model/model_preset)."
                ),
            },
        },
        "required": ["action"],
    }
    assert "READ-ONLY MODE" in tool.description
    result = await tool.execute(action="set", key="max_iterations", value=80)
    assert result == "Error: set is disabled (tools.my.allow_set is false)"
    assert loop.max_iterations != 80


@pytest.mark.asyncio
async def test_allowlisted_commands_preserve_runtime_side_effects(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, allow_set=True)
    tool = _my_tool(loop)

    max_iterations = await tool.execute(
        action="set",
        key="max_iterations",
        value=80,
    )
    retry_mode = await tool.execute(
        action="set",
        key="provider_retry_mode",
        value="persistent",
    )
    scratchpad = await tool.execute(
        action="set",
        key="preference",
        value={"concise": True},
    )

    assert max_iterations == "Set max_iterations = 80 (was 200)"
    assert retry_mode == "Set provider_retry_mode = 'persistent' (was 'standard')"
    assert scratchpad == "Set scratchpad.preference = {'concise': True}"
    assert loop.max_iterations == 80
    assert loop.subagents.max_iterations == 80
    assert loop.provider_retry_mode == "persistent"
    assert tool._runtime_control.snapshot().scratchpad == {
        "preference": {"concise": True},
    }


@pytest.mark.asyncio
async def test_registry_exposes_unchanged_my_tool_actions(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, allow_set=True)

    checked = await loop.tools.execute("my", {"action": "check", "key": "model"})
    changed = await loop.tools.execute(
        "my",
        {"action": "set", "key": "max_iterations", "value": 80},
    )

    assert checked == "model: 'test-model'"
    assert changed == "Set max_iterations = 80 (was 200)"
    assert loop.max_iterations == 80


@pytest.mark.asyncio
async def test_workspace_display_command_cannot_change_path_enforcement(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path, allow_set=True)
    tool = _my_tool(loop)

    result = await tool.execute(action="set", key="workspace", value="elsewhere")

    assert "Set workspace" in result
    assert tool._runtime_control.snapshot().workspace == "elsewhere"
    assert loop.workspace == tmp_path
    assert loop.workspace_scopes.default_workspace == tmp_path
