"""File system tools: read, write, edit."""

from pathlib import Path
from typing import Any, Optional

from loguru import logger

from nanobot.agent.tools.base import Tool


class WorkspaceSecurityError(Exception):
    """Raised when a path operation violates workspace boundaries."""
    pass


def validate_workspace_path(
    path_str: str,
    workspace: Optional[Path],
    restrict_to_workspace: bool = True,
) -> Path:
    """
    Validate and resolve a path, ensuring it stays within the workspace.

    Args:
        path_str: The path string to validate (may contain ~, .., etc.)
        workspace: The workspace root directory
        restrict_to_workspace: If True, enforce path containment

    Returns:
        Resolved absolute Path object

    Raises:
        WorkspaceSecurityError: If path escapes workspace boundaries
        FileNotFoundError: If workspace is required but not configured
    """
    # Input validation - reject empty paths
    if not path_str or not path_str.strip():
        raise WorkspaceSecurityError("Empty path is not allowed")

    # Reject null bytes (defense in depth)
    if "\x00" in path_str:
        raise WorkspaceSecurityError("Invalid characters in path")

    # Expand user home and resolve to absolute path
    resolved = Path(path_str).expanduser().resolve()

    # If restriction is disabled, return resolved path
    if not restrict_to_workspace:
        return resolved

    # Workspace must be configured when restriction is enabled
    if workspace is None:
        raise FileNotFoundError("Workspace not configured but restrict_to_workspace is enabled")

    # Resolve workspace and check containment
    workspace_resolved = workspace.resolve()

    try:
        # This raises ValueError if not relative
        resolved.relative_to(workspace_resolved)
    except ValueError:
        logger.warning(f"SECURITY: Path escape blocked - input={path_str!r} resolved={resolved} workspace={workspace_resolved}")
        raise WorkspaceSecurityError("Access denied: path is outside the allowed workspace")

    return resolved


class ReadFileTool(Tool):
    """Tool to read file contents."""

    def __init__(
        self,
        workspace: Optional[Path] = None,
        restrict_to_workspace: bool = True,
    ):
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a file at the given path."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to read"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            # Validate path against workspace boundaries
            file_path = validate_workspace_path(
                path,
                self.workspace,
                self.restrict_to_workspace,
            )

            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding="utf-8")
            return content
        except WorkspaceSecurityError as e:
            return f"Error: {e}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(
        self,
        workspace: Optional[Path] = None,
        restrict_to_workspace: bool = True,
    ):
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to write to"
                },
                "content": {
                    "type": "string",
                    "description": "The content to write"
                }
            },
            "required": ["path", "content"]
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            # Validate path against workspace boundaries
            file_path = validate_workspace_path(
                path,
                self.workspace,
                self.restrict_to_workspace,
            )

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except WorkspaceSecurityError as e:
            return f"Error: {e}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(
        self,
        workspace: Optional[Path] = None,
        restrict_to_workspace: bool = True,
    ):
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Edit a file by replacing old_text with new_text. The old_text must exist exactly in the file."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to edit"
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace"
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace with"
                }
            },
            "required": ["path", "old_text", "new_text"]
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            # Validate path against workspace boundaries
            file_path = validate_workspace_path(
                path,
                self.workspace,
                self.restrict_to_workspace,
            )

            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return f"Error: old_text not found in file. Make sure it matches exactly."

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {path}"
        except WorkspaceSecurityError as e:
            return f"Error: {e}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


class ListDirTool(Tool):
    """Tool to list directory contents."""

    def __init__(
        self,
        workspace: Optional[Path] = None,
        restrict_to_workspace: bool = True,
    ):
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "List the contents of a directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to list"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            # Validate path against workspace boundaries
            dir_path = validate_workspace_path(
                path,
                self.workspace,
                self.restrict_to_workspace,
            )

            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "[DIR] " if item.is_dir() else "[FILE] "
                items.append(f"{prefix}{item.name}")

            if not items:
                return f"Directory {path} is empty"

            return "\n".join(items)
        except WorkspaceSecurityError as e:
            return f"Error: {e}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
