"""Lens port discovery - deterministic port assignment per workspace."""

import hashlib
import json
from pathlib import Path


def workspace_port(workspace_path: str, base: int = 8765, max_offset: int = 100) -> int:
    """Calculate deterministic port for a workspace.

    Args:
        workspace_path: Absolute path to workspace directory
        base: Starting port number
        max_offset: Maximum port offset from base

    Returns:
        Port number (base to base + max_offset)
    """
    # Normalize path for consistent hashing
    normalized = Path(workspace_path).expanduser().resolve().as_posix()
    h = hashlib.md5(normalized.encode()).hexdigest()
    offset = int(h, 16) % max_offset
    return base + offset


def get_discovery_file() -> Path:
    """Get path to lens port discovery file."""
    return Path.home() / ".blackcat" / ".lens-ports.json"


def read_port_mapping() -> dict[str, int]:
    """Read workspace -> port mapping from discovery file.

    Returns:
        Dict mapping workspace paths to port numbers
    """
    discovery_file = get_discovery_file()
    if not discovery_file.exists():
        return {}
    try:
        with open(discovery_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def write_port_mapping(mapping: dict[str, int]) -> None:
    """Write workspace -> port mapping to discovery file."""
    discovery_file = get_discovery_file()
    discovery_file.parent.mkdir(parents=True, exist_ok=True)
    with open(discovery_file, "w") as f:
        json.dump(mapping, f, indent=2)


def register_workspace_port(workspace_path: str, port: int) -> None:
    """Register a workspace's port in the discovery file.

    Args:
        workspace_path: Absolute path to workspace
        port: Port number the server is listening on
    """
    mapping = read_port_mapping()
    normalized = Path(workspace_path).expanduser().resolve().as_posix()
    mapping[normalized] = port
    write_port_mapping(mapping)


def unregister_workspace_port(workspace_path: str) -> None:
    """Remove a workspace from the discovery file."""
    mapping = read_port_mapping()
    normalized = Path(workspace_path).expanduser().resolve().as_posix()
    if normalized in mapping:
        del mapping[normalized]
        write_port_mapping(mapping)


def get_port_for_workspace(workspace_path: str) -> int:
    """Get the port for a workspace.

    First checks discovery file, then calculates expected port.

    Args:
        workspace_path: Path to workspace (can be relative or absolute)

    Returns:
        Port number to connect to
    """
    # First check if registered in discovery file
    mapping = read_port_mapping()
    normalized = Path(workspace_path).expanduser().resolve().as_posix()

    if normalized in mapping:
        return mapping[normalized]

    # Fall back to calculated port
    return workspace_port(workspace_path)


def find_workspace_for_file(file_path: str, config_workspaces: dict[str, str]) -> tuple[str, int] | None:
    """Find workspace path and port for a file.

    Args:
        file_path: Absolute path to a file
        config_workspaces: Dict from LensConfig.workspaces (alias -> path)

    Returns:
        Tuple of (workspace_path, port) or None if not found
    """
    file_p = Path(file_path).expanduser().resolve()

    # Check discovery file first
    mapping = read_port_mapping()

    # Check all registered workspaces in discovery file
    for ws_path, port in mapping.items():
        ws_p = Path(ws_path)
        try:
            file_p.relative_to(ws_p)
            return ws_path, port
        except ValueError:
            continue

    # Check configured workspaces
    for ws_path in config_workspaces.values():
        ws_p = Path(ws_path).expanduser().resolve()
        try:
            file_p.relative_to(ws_p)
            return str(ws_p), get_port_for_workspace(ws_path)
        except ValueError:
            continue

    return None


def find_workspace_by_alias(alias: str, config_workspaces: dict[str, str]) -> tuple[str, int] | None:
    """Find workspace path and port by alias from config.

    Args:
        alias: Workspace alias from config (e.g., "black-cat-py")
        config_workspaces: Dict from LensConfig.workspaces

    Returns:
        Tuple of (workspace_path, port) or None if not found
    """
    if alias not in config_workspaces:
        return None

    workspace_path = config_workspaces[alias]
    port = get_port_for_workspace(workspace_path)
    return workspace_path, port
