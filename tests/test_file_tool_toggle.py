from types import SimpleNamespace

from blackcat.agent.tools.context import ToolContext
from blackcat.agent.tools.file_state import FileStates
from blackcat.agent.tools.filesystem import FileToolsConfig, ReadFileTool
from blackcat.agent.tools.loader import ToolLoader
from blackcat.agent.tools.registry import ToolRegistry
from blackcat.config.schema import Config, ToolsConfig

FILE_TOOL_NAMES = {
    "apply_patch",
    "edit_file",
    "find_files",
    "grep",
    "list_dir",
    "read_file",
    "write_file",
}


def test_file_tools_enabled_by_default():
    assert FileToolsConfig().enable is True
    assert Config().tools.file.enable is True


def test_file_tool_gate_follows_flag():
    cfg = ToolsConfig()
    cfg.file.enable = False
    assert ReadFileTool.enabled(SimpleNamespace(config=cfg)) is False
    assert ReadFileTool.enabled(SimpleNamespace(config=ToolsConfig())) is True


def test_file_tool_loader_skips_all_builtin_file_tools_when_disabled(tmp_path):
    cfg = ToolsConfig(file=FileToolsConfig(enable=False))
    ctx = ToolContext(
        config=cfg,
        workspace=str(tmp_path),
        file_state_store=FileStates(),
    )
    registry = ToolRegistry()

    ToolLoader().load(ctx, registry)

    assert FILE_TOOL_NAMES.isdisjoint(registry.tool_names)
