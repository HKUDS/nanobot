"""Default tool sets for the agent loop and subagents (composition lives here, not in registry)."""

from collections.abc import Iterable
from pathlib import Path

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.search import GlobTool, GrepTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.config.schema import ExecToolConfig, WebToolsConfig


def build_default_tool_registry(
    workspace: Path,
    *,
    allowed_dir: Path | None,
    extra_read: list[Path] | None,
    exec_config: ExecToolConfig,
    web_config: WebToolsConfig,
    restrict_to_workspace: bool,
    extra_tools: Iterable[Tool] | None = None,
) -> ToolRegistry:
    """
    Core filesystem, shell, and web tools shared by the main agent loop and subagents.

    Pass ``extra_tools`` for loop-only tools (message, spawn, cron, etc.).
    """
    tools: list[Tool] = [
        ReadFileTool(
            workspace=workspace,
            allowed_dir=allowed_dir,
            extra_allowed_dirs=extra_read,
        ),
        WriteFileTool(workspace=workspace, allowed_dir=allowed_dir),
        EditFileTool(workspace=workspace, allowed_dir=allowed_dir),
        ListDirTool(workspace=workspace, allowed_dir=allowed_dir),
        GlobTool(workspace=workspace, allowed_dir=allowed_dir),
        GrepTool(workspace=workspace, allowed_dir=allowed_dir),
        ExecTool(
            timeout=exec_config.timeout,
            working_dir=str(workspace),
            restrict_to_workspace=restrict_to_workspace,
            path_append=exec_config.path_append,
            enable=exec_config.enable,
        ),
        WebSearchTool(
            config=web_config.search,
            proxy=web_config.proxy,
            enable=web_config.enable,
        ),
        WebFetchTool(proxy=web_config.proxy, enable=web_config.enable),
    ]
    if extra_tools:
        tools.extend(extra_tools)
    return ToolRegistry(tools)
