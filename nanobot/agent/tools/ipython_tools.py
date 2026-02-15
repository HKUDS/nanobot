"""
Expose agent tools for use in IPython.

This module allows IPython kernels to access and use agent tools directly.

Usage in IPython:
    from nanobot.agent.tools.ipython_tools import Tools
    
    # Initialize tools
    tools = Tools(workspace="/path/to/workspace")
    
    # List available tools
    tools.list()
    
    # Execute a tool
    result = await tools.read_file(path="/home/user/file.txt")
    result = await tools.exec(command="ls -la")
    result = await tools.web_search(query="python asyncio")
    result = await tools.message(content="Hello!", channel="telegram", chat_id="123456")
"""

import asyncio
from pathlib import Path
from typing import Any, Callable, Awaitable

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.models import ListModelsTool, TestModelTool, AddModelTool, ChangeModelTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.gateway import RestartGatewayTool
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.context import ClearContextTool, CompactContextTool
from nanobot.bus.events import OutboundMessage


# Global context for sharing gateway state with embedded IPython kernels
_gateway_context: dict[str, Any] = {
    "message_callback": None,
    "agent": None,
    "cron_service": None,
    "subagent_manager": None,
    "default_channel": "",
    "default_chat_id": "",
}


def set_gateway_context(
    message_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
    agent: Any = None,
    cron_service: Any = None,
    subagent_manager: Any = None,
    default_channel: str = "",
    default_chat_id: str = "",
) -> None:
    """
    Set the global gateway context for IPython tools.
    
    This is called by the gateway to share its runtime context with
    embedded IPython kernels.
    """
    if message_callback is not None:
        _gateway_context["message_callback"] = message_callback
    if agent is not None:
        _gateway_context["agent"] = agent
    if cron_service is not None:
        _gateway_context["cron_service"] = cron_service
    if subagent_manager is not None:
        _gateway_context["subagent_manager"] = subagent_manager
    if default_channel:
        _gateway_context["default_channel"] = default_channel
    if default_chat_id:
        _gateway_context["default_chat_id"] = default_chat_id


def get_gateway_context() -> dict[str, Any]:
    """Get the current gateway context."""
    return _gateway_context.copy()


class Tools:
    """
    Agent tools exposed for IPython use.
    
    This class wraps the tool registry and provides a convenient interface
    for using agent tools from IPython.
    
    Example:
        >>> from nanobot.agent.tools.ipython_tools import Tools
        >>> tools = Tools()
        >>> 
        >>> # List available tools
        >>> tools.list()
        ['read_file', 'write_file', 'edit_file', 'list_dir', 'exec', ...]
        >>> 
        >>> # Execute tools (async)
        >>> result = await tools.read_file(path="/etc/hostname")
        >>> print(result)
    """
    
    def __init__(
        self,
        workspace: str | Path | None = None,
        timeout: int = 60,
        restrict_to_workspace: bool = False,
        default_channel: str = "",
        default_chat_id: str = "",
        message_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        agent: Any = None,
        cron_service: Any = None,
        subagent_manager: Any = None,
    ):
        """
        Initialize tools.
        
        Args:
            workspace: Working directory for file operations and shell commands.
            timeout: Default timeout for shell commands.
            restrict_to_workspace: If True, restrict file/shell operations to workspace.
            default_channel: Default channel for message tool (e.g., "telegram").
            default_chat_id: Default chat ID for message tool.
            message_callback: Async callback function for sending messages.
            agent: Agent instance (required for some tools like model/context management).
            cron_service: CronService instance (required for cron tool).
            subagent_manager: SubagentManager instance (required for spawn tool).
        """
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self.timeout = timeout
        self.restrict_to_workspace = restrict_to_workspace
        self.default_channel = default_channel
        self.default_chat_id = default_chat_id
        self._message_callback = message_callback
        self._agent = agent
        self._cron_service = cron_service
        self._subagent_manager = subagent_manager
        
        self._registry = ToolRegistry()
        self._register_tools()
    
    def _register_tools(self) -> None:
        """Register all available tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        
        # File tools
        self._registry.register(ReadFileTool(allowed_dir=allowed_dir))
        self._registry.register(WriteFileTool(allowed_dir=allowed_dir))
        self._registry.register(EditFileTool(allowed_dir=allowed_dir))
        self._registry.register(ListDirTool(allowed_dir=allowed_dir))
        
        # Shell tool
        self._registry.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))
        
        # Web tools
        self._registry.register(WebSearchTool())
        self._registry.register(WebFetchTool())
        
        # Model tools - some require agent, some don't
        if self._agent:
            self._registry.register(ListModelsTool(agent=self._agent))
            self._registry.register(TestModelTool(self._agent))
            self._registry.register(ChangeModelTool(self._agent))
        else:
            # ListModelsTool can work without agent (just won't show current model)
            self._registry.register(ListModelsTool())
        # AddModelTool doesn't require agent
        self._registry.register(AddModelTool())
        
        # Message tool (with default no-op callback - can be set later)
        self._message_tool = MessageTool(
            default_channel=self.default_channel,
            default_chat_id=self.default_chat_id,
        )
        if self._message_callback:
            self._message_tool.set_send_callback(self._message_callback)
        self._registry.register(self._message_tool)
        
        # Gateway tool
        self._registry.register(RestartGatewayTool())
        
        # Cron tool - requires cron_service
        if self._cron_service:
            self._registry.register(CronTool(self._cron_service))
        
        # Spawn tool - requires subagent_manager
        if self._subagent_manager:
            self._registry.register(SpawnTool(self._subagent_manager))
        
        # Context tools - require agent
        if self._agent:
            self._registry.register(ClearContextTool(self._agent))
            self._registry.register(CompactContextTool(self._agent))
    
    def list(self) -> list[str]:
        """
        List all available tool names.
        
        Returns:
            List of tool names.
        """
        return self._registry.tool_names
    
    def schemas(self) -> list[dict[str, Any]]:
        """
        Get JSON schemas for all tools.
        
        Returns:
            List of tool schemas in OpenAI format.
        """
        return self._registry.get_definitions()
    
    def help(self, tool_name: str) -> str:
        """
        Get help for a specific tool.
        
        Args:
            tool_name: Name of the tool.
        
        Returns:
            Help text describing the tool and its parameters.
        """
        tool = self._registry.get(tool_name)
        if not tool:
            return f"Tool '{tool_name}' not found. Available: {self.list()}"
        
        import json
        return f"{tool.name}: {tool.description}\n\nParameters:\n{json.dumps(tool.parameters, indent=2)}"
    
    async def execute(self, tool_name: str, **kwargs) -> str:
        """
        Execute a tool by name with given parameters.
        
        Args:
            tool_name: Name of the tool to execute.
            **kwargs: Tool-specific parameters.
        
        Returns:
            Tool execution result as string.
        """
        return await self._registry.execute(tool_name, kwargs)
    
    def __getattr__(self, name: str):
        """
        Allow calling tools as methods.
        
        This enables syntax like: await tools.read_file(path="...")
        """
        if name.startswith("_"):
            raise AttributeError(name)
        
        tool = self._registry.get(name)
        if tool:
            async def wrapper(**kwargs):
                return await self._registry.execute(name, kwargs)
            wrapper.__name__ = name
            wrapper.__doc__ = f"{tool.description}\n\nSee tools.help('{name}') for parameters."
            return wrapper
        
        raise AttributeError(f"No tool named '{name}'. Available: {self.list()}")
    
    def __dir__(self):
        """Include tool names in dir() output."""
        return list(super().__dir__()) + self.list()


# Convenience function for quick access
def get_tools(workspace: str | Path | None = None, use_gateway_context: bool = True, **kwargs) -> Tools:
    """
    Get a Tools instance for the given workspace.
    
    Args:
        workspace: Working directory. Defaults to current directory.
        use_gateway_context: If True, use the global gateway context for callbacks.
        **kwargs: Additional arguments passed to Tools constructor.
    
    Returns:
        Tools instance.
    
    Example:
        >>> from nanobot.agent.tools.ipython_tools import get_tools
        >>> tools = get_tools()
        >>> await tools.exec(command="echo hello")
    """
    if use_gateway_context:
        # Merge gateway context with explicit kwargs (kwargs take precedence)
        ctx = get_gateway_context()
        final_kwargs = {
            "message_callback": ctx.get("message_callback"),
            "agent": ctx.get("agent"),
            "cron_service": ctx.get("cron_service"),
            "subagent_manager": ctx.get("subagent_manager"),
            "default_channel": ctx.get("default_channel", ""),
            "default_chat_id": ctx.get("default_chat_id", ""),
        }
        final_kwargs.update(kwargs)
        return Tools(workspace=workspace, **final_kwargs)
    return Tools(workspace=workspace, **kwargs)
