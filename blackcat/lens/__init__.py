"""Lens: Code intelligence via VS Code extension."""

from .client import LensClient
from .discovery import (
    find_workspace_by_alias,
    find_workspace_for_file,
    get_port_for_workspace,
    read_port_mapping,
    register_workspace_port,
    unregister_workspace_port,
    workspace_port,
)
from .formatting import format_diagnostics

__all__ = [
    "LensClient",
    "format_diagnostics",
    "workspace_port",
    "read_port_mapping",
    "register_workspace_port",
    "unregister_workspace_port",
    "get_port_for_workspace",
    "find_workspace_by_alias",
    "find_workspace_for_file",
]
