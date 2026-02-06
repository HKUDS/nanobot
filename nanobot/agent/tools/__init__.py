"""Agent tools module."""

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry

# Optional A2A client tool (requires a2a-sdk)
try:
    from nanobot.agent.tools.a2a_client import A2AClientTool
    A2A_TOOL_AVAILABLE = True
except ImportError:
    A2AClientTool = None  # type: ignore
    A2A_TOOL_AVAILABLE = False

__all__ = ["Tool", "ToolRegistry", "A2AClientTool", "A2A_TOOL_AVAILABLE"]
