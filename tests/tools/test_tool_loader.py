"""Tests for tool plugin architecture: ToolLoader, ToolContext, metadata."""
from __future__ import annotations

from dataclasses import fields
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.base import Tool


class _MinimalTool(Tool):
    @property
    def name(self) -> str:
        return "test_minimal"

    @property
    def description(self) -> str:
        return "A test tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> Any:
        return "ok"


def test_tool_default_config_cls_is_none():
    assert _MinimalTool.config_cls() is None


def test_tool_default_config_key_is_empty():
    assert _MinimalTool.config_key == ""


def test_tool_default_enabled_is_true():
    assert _MinimalTool.enabled(None) is True


def test_tool_default_create_returns_instance():
    tool = _MinimalTool.create(None)
    assert isinstance(tool, _MinimalTool)
    assert tool.name == "test_minimal"


def test_tool_plugin_discoverable_default_is_true():
    assert _MinimalTool._plugin_discoverable is True


# --- ToolContext tests ---

from nanobot.agent.tools.context import ToolContext


def test_tool_context_has_required_fields():
    field_names = {f.name for f in fields(ToolContext)}
    required = {
        "config", "workspace", "bus", "subagent_manager",
        "cron_service", "file_state_store", "provider_snapshot_loader",
        "image_generation_provider_configs", "timezone",
    }
    assert required <= field_names


def test_tool_context_defaults():
    ctx = ToolContext(config=None, workspace="/tmp")
    assert ctx.bus is None
    assert ctx.subagent_manager is None
    assert ctx.cron_service is None
    assert ctx.provider_snapshot_loader is None
    assert ctx.image_generation_provider_configs is None
    assert ctx.timezone == "UTC"


# --- ToolLoader tests ---

from nanobot.agent.tools.loader import ToolLoader, _SKIP_MODULES


def test_skip_modules_excludes_infrastructure():
    infra = {"base", "schema", "registry", "context", "loader", "config",
             "file_state", "sandbox", "mcp", "__init__"}
    assert infra <= _SKIP_MODULES


def test_discover_finds_concrete_tools():
    loader = ToolLoader()
    discovered = loader.discover()
    class_names = {cls.__name__ for cls in discovered}
    assert "ExecTool" in class_names
    assert "MessageTool" in class_names
    assert "SpawnTool" in class_names


def test_discover_excludes_abstract_and_mcp():
    loader = ToolLoader()
    discovered = loader.discover()
    class_names = {cls.__name__ for cls in discovered}
    assert "_FsTool" not in class_names
    assert "_SearchTool" not in class_names
    assert "MCPToolWrapper" not in class_names
    assert "MCPResourceWrapper" not in class_names
    assert "MCPPromptWrapper" not in class_names


def test_discover_skips_private_classes():
    loader = ToolLoader()
    discovered = loader.discover()
    for cls in discovered:
        assert not cls.__name__.startswith("_")


# --- Task 4: _FsTool.create() ---

from pathlib import Path


def test_fs_tool_create_builds_from_context():
    from nanobot.agent.tools.filesystem import ReadFileTool
    mock_config = MagicMock()
    mock_config.restrict_to_workspace = False
    mock_config.exec.sandbox = ""
    ctx = ToolContext(config=mock_config, workspace="/tmp/test")
    tool = ReadFileTool.create(ctx)
    assert isinstance(tool, ReadFileTool)
    assert tool._workspace == Path("/tmp/test")


def test_fs_tool_create_respects_restrict_to_workspace():
    from nanobot.agent.tools.filesystem import ReadFileTool
    mock_config = MagicMock()
    mock_config.restrict_to_workspace = True
    mock_config.exec.sandbox = ""
    ctx = ToolContext(config=mock_config, workspace="/tmp/test")
    tool = ReadFileTool.create(ctx)
    assert tool._allowed_dir == Path("/tmp/test")


def test_fs_tool_create_respects_sandbox():
    from nanobot.agent.tools.filesystem import ReadFileTool
    mock_config = MagicMock()
    mock_config.restrict_to_workspace = False
    mock_config.exec.sandbox = "bwrap"
    ctx = ToolContext(config=mock_config, workspace="/tmp/test")
    tool = ReadFileTool.create(ctx)
    assert tool._allowed_dir == Path("/tmp/test")


# --- Task 5: MessageTool, SpawnTool, CronTool ---


async def test_message_tool_create():
    from nanobot.agent.tools.message import MessageTool
    mock_bus = MagicMock()
    mock_config = MagicMock()
    ctx = ToolContext(config=mock_config, workspace="/tmp", bus=mock_bus)
    tool = MessageTool.create(ctx)
    assert isinstance(tool, MessageTool)


def test_spawn_tool_create():
    from nanobot.agent.tools.spawn import SpawnTool
    mock_mgr = MagicMock()
    mock_config = MagicMock()
    ctx = ToolContext(config=mock_config, workspace="/tmp", subagent_manager=mock_mgr)
    tool = SpawnTool.create(ctx)
    assert isinstance(tool, SpawnTool)


def test_cron_tool_enabled_without_service():
    from nanobot.agent.tools.cron import CronTool
    mock_config = MagicMock()
    ctx = ToolContext(config=mock_config, workspace="/tmp", cron_service=None)
    assert CronTool.enabled(ctx) is False


def test_cron_tool_enabled_with_service():
    from nanobot.agent.tools.cron import CronTool
    mock_service = MagicMock()
    mock_config = MagicMock()
    ctx = ToolContext(config=mock_config, workspace="/tmp", cron_service=mock_service)
    assert CronTool.enabled(ctx) is True


def test_cron_tool_create():
    from nanobot.agent.tools.cron import CronTool
    mock_service = MagicMock()
    mock_config = MagicMock()
    ctx = ToolContext(
        config=mock_config, workspace="/tmp",
        cron_service=mock_service, timezone="Asia/Shanghai",
    )
    tool = CronTool.create(ctx)
    assert isinstance(tool, CronTool)


# --- Task 6: ExecTool, WebTools, ImageGenerationTool ---


def test_exec_tool_config_cls():
    from nanobot.agent.tools.shell import ExecTool, ExecToolConfig
    assert ExecTool.config_cls() is ExecToolConfig
    assert ExecTool.config_key == "exec"


def test_exec_tool_enabled():
    from nanobot.agent.tools.shell import ExecTool
    mock_config = MagicMock()
    mock_config.exec.enable = True
    ctx = ToolContext(config=mock_config, workspace="/tmp")
    assert ExecTool.enabled(ctx) is True
    mock_config.exec.enable = False
    assert ExecTool.enabled(ctx) is False


def test_exec_tool_create():
    from nanobot.agent.tools.shell import ExecTool
    mock_config = MagicMock()
    mock_config.exec.enable = True
    mock_config.exec.timeout = 120
    mock_config.exec.sandbox = ""
    mock_config.exec.path_append = ""
    mock_config.exec.allowed_env_keys = []
    mock_config.exec.allow_patterns = []
    mock_config.exec.deny_patterns = []
    mock_config.restrict_to_workspace = False
    ctx = ToolContext(config=mock_config, workspace="/tmp")
    tool = ExecTool.create(ctx)
    assert isinstance(tool, ExecTool)


def test_web_tools_config_cls():
    from nanobot.agent.tools.web import WebSearchTool, WebFetchTool, WebToolsConfig
    assert WebSearchTool.config_key == "web"
    assert WebSearchTool.config_cls() is WebToolsConfig
    assert WebFetchTool.config_key == "web"
    assert WebFetchTool.config_cls() is WebToolsConfig


def test_web_tools_enabled():
    from nanobot.agent.tools.web import WebSearchTool
    mock_config = MagicMock()
    mock_config.web.enable = True
    ctx = ToolContext(config=mock_config, workspace="/tmp")
    assert WebSearchTool.enabled(ctx) is True
    mock_config.web.enable = False
    assert WebSearchTool.enabled(ctx) is False


def test_web_search_tool_create():
    from nanobot.agent.tools.web import WebSearchTool
    mock_config = MagicMock()
    mock_config.web.enable = True
    mock_config.web.search = MagicMock()
    mock_config.web.proxy = None
    mock_config.web.user_agent = None
    ctx = ToolContext(config=mock_config, workspace="/tmp")
    tool = WebSearchTool.create(ctx)
    assert isinstance(tool, WebSearchTool)


def test_web_fetch_tool_create():
    from nanobot.agent.tools.web import WebFetchTool
    mock_config = MagicMock()
    mock_config.web.enable = True
    mock_config.web.fetch = MagicMock()
    mock_config.web.proxy = None
    mock_config.web.user_agent = None
    ctx = ToolContext(config=mock_config, workspace="/tmp")
    tool = WebFetchTool.create(ctx)
    assert isinstance(tool, WebFetchTool)


def test_image_gen_tool_config_cls():
    from nanobot.agent.tools.image_generation import ImageGenerationTool, ImageGenerationToolConfig
    assert ImageGenerationTool.config_key == "image_generation"
    assert ImageGenerationTool.config_cls() is ImageGenerationToolConfig


def test_image_gen_tool_enabled():
    from nanobot.agent.tools.image_generation import ImageGenerationTool
    mock_config = MagicMock()
    mock_config.image_generation.enabled = True
    ctx = ToolContext(config=mock_config, workspace="/tmp")
    assert ImageGenerationTool.enabled(ctx) is True
    mock_config.image_generation.enabled = False
    assert ImageGenerationTool.enabled(ctx) is False


def test_image_gen_tool_create():
    from nanobot.agent.tools.image_generation import ImageGenerationTool
    mock_config = MagicMock()
    mock_config.image_generation = MagicMock()
    ctx = ToolContext(
        config=mock_config, workspace="/tmp",
        image_generation_provider_configs={"openrouter": MagicMock()},
    )
    tool = ImageGenerationTool.create(ctx)
    assert isinstance(tool, ImageGenerationTool)


# --- Task 7: MyToolConfig + MCP wrappers ---


def test_my_tool_config_cls():
    from nanobot.agent.tools.self import MyTool, MyToolConfig
    assert MyTool.config_key == "my"
    assert MyTool.config_cls() is MyToolConfig


def test_my_tool_enabled():
    from nanobot.agent.tools.self import MyTool
    mock_config = MagicMock()
    mock_config.my.enable = True
    ctx = ToolContext(config=mock_config, workspace="/tmp")
    assert MyTool.enabled(ctx) is True
    mock_config.my.enable = False
    assert MyTool.enabled(ctx) is False


def test_mcp_wrappers_not_discoverable():
    from nanobot.agent.tools.mcp import MCPToolWrapper, MCPResourceWrapper, MCPPromptWrapper
    assert MCPToolWrapper._plugin_discoverable is False
    assert MCPResourceWrapper._plugin_discoverable is False
    assert MCPPromptWrapper._plugin_discoverable is False


# --- Task 8: Config round-trip tests ---


def test_config_round_trip():
    """Verify config serialization is unchanged after moving config classes."""
    from nanobot.config.schema import Config

    config_dict = {
        "tools": {
            "web": {"enable": True, "search": {"provider": "brave", "api_key": "test"}},
            "exec": {"enable": False, "timeout": 120},
            "my": {"allowSet": True},
            "imageGeneration": {"enabled": True, "provider": "openrouter"},
        }
    }
    config = Config.model_validate(config_dict)
    dumped = config.model_dump(mode="json", by_alias=True)

    assert dumped["tools"]["my"]["allowSet"] is True
    assert dumped["tools"]["imageGeneration"]["enabled"] is True
    assert config.tools.exec.enable is False
    assert config.tools.exec.timeout == 120
    assert config.tools.web.search.provider == "brave"


def test_config_defaults():
    """Verify default values match the original hardcoded schema."""
    from nanobot.config.schema import Config

    config = Config.model_validate({})
    assert config.tools.exec.enable is True
    assert config.tools.exec.timeout == 60
    assert config.tools.web.enable is True
    assert config.tools.web.search.provider == "duckduckgo"
    assert config.tools.my.enable is True
    assert config.tools.my.allow_set is False
    assert config.tools.image_generation.enabled is False
    assert config.tools.restrict_to_workspace is False


# --- Task 10: Integration test ---


def test_loader_registers_same_tools_as_old_hardcoded():
    """Verify the loader produces the same tool set as the old _register_default_tools."""
    from nanobot.agent.tools.loader import ToolLoader
    from nanobot.agent.tools.registry import ToolRegistry

    mock_config = MagicMock()
    mock_config.exec.enable = True
    mock_config.exec.timeout = 60
    mock_config.exec.sandbox = ""
    mock_config.exec.path_append = ""
    mock_config.exec.allowed_env_keys = []
    mock_config.exec.allow_patterns = []
    mock_config.exec.deny_patterns = []
    mock_config.restrict_to_workspace = False
    mock_config.web.enable = True
    mock_config.web.search = MagicMock()
    mock_config.web.fetch = MagicMock()
    mock_config.web.proxy = None
    mock_config.web.user_agent = None
    mock_config.image_generation.enabled = False
    mock_config.my.enable = True

    ctx = ToolContext(
        config=mock_config,
        workspace="/tmp",
        bus=MagicMock(),
        subagent_manager=MagicMock(),
        cron_service=MagicMock(),
        timezone="UTC",
    )
    registry = ToolRegistry()
    loader = ToolLoader()
    registered = loader.load(ctx, registry)

    expected = {
        "read_file", "write_file", "edit_file", "list_dir",
        "glob", "grep", "notebook_edit", "exec", "web_search", "web_fetch",
        "message", "spawn", "cron",
    }
    actual = set(registered)
    assert expected <= actual, f"Missing tools: {expected - actual}"
