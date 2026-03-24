"""Tool registry for dynamic tool management."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.config.schema import ExecToolConfig, WebSearchConfig


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> Any:
        """Execute a tool by name with given parameters."""
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        try:
            # Attempt to cast parameters to match schema types
            params = tool.cast_params(params)
            
            # Validate parameters
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            result = await tool.execute(**params)
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT
            return result
        except Exception as e:
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def build_base_tools(
    workspace: Path,
    exec_config: "ExecToolConfig",
    web_search_config: "WebSearchConfig | None" = None,
    web_proxy: str | None = None,
    restrict_to_workspace: bool = False,
    extra_read_dirs: list[Path] | None = None,
) -> ToolRegistry:
    """Build a ToolRegistry pre-loaded with filesystem, shell, and web tools."""
    from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
    from nanobot.agent.tools.shell import ExecTool
    from nanobot.agent.tools.web import WebFetchTool, WebSearchTool

    tools = ToolRegistry()
    allowed_dir = workspace if restrict_to_workspace else None
    tools.register(ReadFileTool(workspace=workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read_dirs))
    for cls in (WriteFileTool, EditFileTool, ListDirTool):
        tools.register(cls(workspace=workspace, allowed_dir=allowed_dir))
    tools.register(ExecTool(
        working_dir=str(workspace),
        timeout=exec_config.timeout,
        restrict_to_workspace=restrict_to_workspace,
        path_append=exec_config.path_append,
    ))
    tools.register(WebSearchTool(config=web_search_config, proxy=web_proxy))
    tools.register(WebFetchTool(proxy=web_proxy))
    return tools
