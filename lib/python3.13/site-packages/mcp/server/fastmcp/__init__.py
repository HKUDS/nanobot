"""FastMCP - A more ergonomic interface for MCP servers."""

from importlib.metadata import version

from mcp.types import Icon

from .server import Context, FastMCP
from .utilities.types import Audio, Image

__version__ = version("mcp")
__all__ = ["FastMCP", "Context", "Image", "Audio", "Icon"]
