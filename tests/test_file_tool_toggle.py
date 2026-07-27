from types import SimpleNamespace

import pytest

from nanobot.agent.tools.context import (
    ToolContext,
    bind_attachment_paths,
    reset_attachment_paths,
)
from nanobot.agent.tools.file_state import FileStates
from nanobot.agent.tools.filesystem import (
    AttachmentReadFileTool,
    FileToolsConfig,
    ReadFileTool,
)
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import Config, ToolsConfig

GENERAL_FILE_TOOL_NAMES = {
    "apply_patch",
    "edit_file",
    "find_files",
    "grep",
    "list_dir",
    "write_file",
}


def test_file_tools_enabled_by_default():
    assert FileToolsConfig().enable is True
    assert Config().tools.file.enable is True


def test_file_tool_gate_follows_flag():
    cfg = ToolsConfig()
    cfg.file.enable = False
    assert ReadFileTool.enabled(SimpleNamespace(config=cfg)) is False
    assert AttachmentReadFileTool.enabled(SimpleNamespace(config=cfg)) is True
    assert ReadFileTool.enabled(SimpleNamespace(config=ToolsConfig())) is True
    assert AttachmentReadFileTool.enabled(SimpleNamespace(config=ToolsConfig())) is False


@pytest.mark.asyncio
async def test_file_tool_loader_keeps_only_attachment_reader_when_disabled(tmp_path):
    cfg = ToolsConfig(file=FileToolsConfig(enable=False))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    ctx = ToolContext(
        config=cfg,
        workspace=str(workspace),
        file_state_store=FileStates(),
    )
    registry = ToolRegistry()

    ToolLoader().load(ctx, registry)

    assert GENERAL_FILE_TOOL_NAMES.isdisjoint(registry.tool_names)
    tool = registry.get("read_file")
    assert isinstance(tool, AttachmentReadFileTool)

    workspace_file = workspace / "workspace.txt"
    workspace_file.write_text("not available", encoding="utf-8")
    assert "Only user-uploaded attachments" in await tool.execute(path=str(workspace_file))

    attachment = tmp_path / "custom-media" / "attachment.txt"
    attachment.parent.mkdir()
    attachment.write_text("attachment body", encoding="utf-8")
    sibling = attachment.parent / "sibling.txt"
    sibling.write_text("must stay private", encoding="utf-8")
    token = bind_attachment_paths([attachment])
    try:
        result = await tool.execute(path=str(attachment))
        sibling_result = await tool.execute(path=str(sibling))
    finally:
        reset_attachment_paths(token)

    assert "attachment body" in result
    assert "outside allowed directory" in sibling_result
    assert "must stay private" not in sibling_result
