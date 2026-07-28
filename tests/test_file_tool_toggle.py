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


class _PluginReadFileTool(ReadFileTool):
    @classmethod
    def enabled(cls, ctx):
        return True

    @classmethod
    def create(cls, ctx):
        return cls(workspace=ctx.workspace)

    async def execute(self, **kwargs):
        return "external plugin read"


def test_file_tools_enabled_by_default():
    assert FileToolsConfig().enable is True
    assert FileToolsConfig().allow_attachment_read is False
    assert Config().tools.file.enable is True
    assert Config().tools.file.allow_attachment_read is False


def test_file_tool_gate_follows_flag():
    cfg = ToolsConfig()
    cfg.file.enable = False
    assert ReadFileTool.enabled(SimpleNamespace(config=cfg)) is False
    assert AttachmentReadFileTool.enabled(SimpleNamespace(config=cfg)) is False
    cfg.file.allow_attachment_read = True
    assert AttachmentReadFileTool.enabled(SimpleNamespace(config=cfg)) is True
    assert ReadFileTool.enabled(SimpleNamespace(config=ToolsConfig())) is True
    assert AttachmentReadFileTool.enabled(SimpleNamespace(config=ToolsConfig())) is False


def test_file_tool_config_accepts_attachment_read_camel_case():
    cfg = FileToolsConfig.model_validate(
        {"enable": False, "allowAttachmentRead": True},
    )

    assert cfg.allow_attachment_read is True


def test_file_tool_loader_disables_all_builtin_file_access_by_default(tmp_path):
    cfg = ToolsConfig(file=FileToolsConfig(enable=False))
    ctx = ToolContext(
        config=cfg,
        workspace=str(tmp_path),
        file_state_store=FileStates(),
    )
    registry = ToolRegistry()

    ToolLoader().load(ctx, registry)

    assert GENERAL_FILE_TOOL_NAMES.isdisjoint(registry.tool_names)
    assert registry.get("read_file") is None


@pytest.mark.asyncio
async def test_file_tool_loader_keeps_only_attachment_reader_when_disabled(tmp_path):
    cfg = ToolsConfig(
        file=FileToolsConfig(
            enable=False,
            allow_attachment_read=True,
        )
    )
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


@pytest.mark.parametrize(
    ("file_tools_enabled", "expected_result"),
    [
        (False, "external plugin read"),
        (True, "1| built-in read"),
    ],
)
@pytest.mark.asyncio
async def test_external_read_file_plugin_only_replaces_attachment_fallback(
    tmp_path,
    monkeypatch,
    file_tools_enabled,
    expected_result,
):
    workspace_file = tmp_path / "workspace.txt"
    workspace_file.write_text("built-in read", encoding="utf-8")
    cfg = ToolsConfig(
        file=FileToolsConfig(
            enable=file_tools_enabled,
            allow_attachment_read=not file_tools_enabled,
        )
    )
    ctx = ToolContext(
        config=cfg,
        workspace=str(tmp_path),
        file_state_store=FileStates(),
    )
    registry = ToolRegistry()
    loader = ToolLoader()
    monkeypatch.setattr(
        loader,
        "_discover_plugins",
        lambda: {"external_read_file": _PluginReadFileTool},
    )

    loader.load(ctx, registry)

    result = await registry.get("read_file").execute(path=str(workspace_file))
    assert expected_result in result
