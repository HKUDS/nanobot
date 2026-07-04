"""Tests for SubagentManager."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager, SubagentStatus
from nanobot.agent.tools.filesystem import FileToolsConfig
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMProvider


@pytest.mark.asyncio
async def test_subagent_uses_tool_loader():
    """Verify subagent registers tools via ToolLoader, not hard-coded imports."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=Path("/tmp"),
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
    )
    tools, _ = await sm._build_tools()
    assert tools.has("read_file")
    assert tools.has("write_file")
    assert not tools.has("message")
    assert not tools.has("spawn")


@pytest.mark.asyncio
async def test_subagent_build_tools_isolates_file_read_state(tmp_path):
    """Each spawned subagent needs a fresh file-state cache."""
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
    )

    first_read = (await sm._build_tools())[0].get("read_file")
    second_read = (await sm._build_tools())[0].get("read_file")

    assert first_read is not second_read
    assert (await first_read.execute(path="note.txt")).startswith("1| hello")
    second_result = await second_read.execute(path="note.txt")
    assert second_result.startswith("1| hello")
    assert "File unchanged" not in second_result


@pytest.mark.asyncio
async def test_subagent_respects_file_tool_toggle(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
        tools_config=ToolsConfig(file=FileToolsConfig(enable=False)),
    )

    tools, _ = await sm._build_tools()

    file_tools = {
        "apply_patch",
        "edit_file",
        "find_files",
        "grep",
        "list_dir",
        "read_file",
        "write_file",
    }
    assert file_tools.isdisjoint(tools.tool_names)


@pytest.mark.asyncio
async def test_subagent_forwards_fail_on_tool_error_to_runner(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
        fail_on_tool_error=False,
    )
    sm.runner.run = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    sm._announce_result = AsyncMock()

    status = SubagentStatus(
        task_id="t1",
        label="label",
        task_description="task",
        started_at=0.0,
    )

    await sm._run_subagent("t1", "task", "label", {"channel": "cli", "chat_id": "direct"}, status)

    spec = sm.runner.run.call_args.args[0]
    assert spec.fail_on_tool_error is False


def _make_sm_with_mcps(tmp_path):
    """SubagentManager with generic MCP servers + a config-driven specialist map."""
    from nanobot.config.schema import MCPServerConfig
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    return SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
        tools_config=ToolsConfig(
            mcp_servers={
                "db": MCPServerConfig(command="echo"),
                "comms": MCPServerConfig(command="echo"),
                "media": MCPServerConfig(command="echo"),
            },
            subagent_specialists={
                "analyst": ["db"],
                "assistant": ["comms"],
                "creator": ["media", "db"],
            },
        ),
    )


def test_specialist_from_label(tmp_path):
    sm = _make_sm_with_mcps(tmp_path)
    assert sm._specialist_from_label("analyst run") == "analyst"
    assert sm._specialist_from_label("creator: promo") == "creator"
    assert sm._specialist_from_label("Assistant") == "assistant"
    assert sm._specialist_from_label("random task") is None
    assert sm._specialist_from_label(None) is None


def test_specialist_inherits_only_its_mcps(tmp_path):
    sm = _make_sm_with_mcps(tmp_path)
    assert set(sm._subagent_tools_config("analyst").mcp_servers) == {"db"}
    assert set(sm._subagent_tools_config("assistant").mcp_servers) == {"comms"}
    assert set(sm._subagent_tools_config("creator").mcp_servers) == {"media", "db"}


def test_generic_subagent_inherits_no_mcps(tmp_path):
    sm = _make_sm_with_mcps(tmp_path)
    assert sm._subagent_tools_config(None).mcp_servers == {}
    assert sm._subagent_tools_config("unknown").mcp_servers == {}


def test_no_specialist_config_means_no_inheritance(tmp_path):
    """With no subagent_specialists configured, behavior is the previous default."""
    from nanobot.config.schema import MCPServerConfig
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
        tools_config=ToolsConfig(mcp_servers={"db": MCPServerConfig(command="echo")}),
    )
    assert sm._specialist_from_label("analyst run") is None
    assert sm._subagent_tools_config("analyst").mcp_servers == {}
