"""File system tools: read, write, edit."""

from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


def _validate_path(path: str, base_dir: Path | None = None) -> tuple[bool, str]:
    """Validate file path is within allowed directory.
    
    Args:
        path: The file path to validate
        base_dir: Base directory to restrict access to. If None, allows all paths.
    
    Returns:
        Tuple of (is_valid, error_message_or_valid_path)
    """
    if not base_dir:
        return True, path  # No restriction
    
    try:
        resolved_path = Path(path).expanduser().resolve()
        base_resolved = base_dir.resolve()
        
        # Check if path is within base directory
        resolved_path.relative_to(base_resolved)
        return True, str(resolved_path)
    except ValueError:
        return False, f"Access denied: {path} is outside allowed directory {base_dir}"
    except Exception as e:
        return False, f"Invalid path: {str(e)}"


class ReadFileTool(Tool):
    """Tool to read file contents."""


class ReadFileTool(Tool):
    """Tool to read file contents."""
    
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
        # Input validation
        if len(path) > 500:
            return "Error: Path too long"
        
        # Security: Validate path is within workspace
        WORKSPACE_DIR = Path.home() / ".nanobot" / "workspace"
        is_valid, result = _validate_path(path, base_dir=WORKSPACE_DIR)
        if not is_valid:
            return result  # error message
        
        # Audit logging
        logger.warning(f"File read operation: {path[:50]}{'...' if len(path) > 50 else ''}")
        
        try:
            file_path = Path(result)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"
            
            content = file_path.read_text(encoding="utf-8")
            return content
        except PermissionError:
            return f"Error: Permission denied"
        except Exception as e:
            return f"Error reading file"


class WriteFileTool(Tool):
    """Tool to write content to a file."""
    
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
        # Security: Validate path is within workspace
        WORKSPACE_DIR = Path.home() / ".nanobot" / "workspace"
        is_valid, result = _validate_path(path, base_dir=WORKSPACE_DIR)
        if not is_valid:
            return result  # error message
        
        try:
            file_path = Path(result)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except PermissionError:
            return f"Error: Permission denied"
        except Exception as e:
            return f"Error writing file"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""
    
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
        # Security: Validate path is within workspace
        WORKSPACE_DIR = Path.home() / ".nanobot" / "workspace"
        is_valid, result = _validate_path(path, base_dir=WORKSPACE_DIR)
        if not is_valid:
            return result  # error message
        
        try:
            file_path = Path(result)
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
        except PermissionError:
            return f"Error: Permission denied"
        except Exception as e:
            return f"Error editing file"


class ListDirTool(Tool):
    """Tool to list directory contents."""
    
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
        # Security: Validate path is within workspace
        WORKSPACE_DIR = Path.home() / ".nanobot" / "workspace"
        is_valid, result = _validate_path(path, base_dir=WORKSPACE_DIR)
        if not is_valid:
            return result  # error message
        
        try:
            dir_path = Path(result)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"
            
            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")
            
            if not items:
                return f"Directory {path} is empty"
            
            return "\n".join(items)
        except PermissionError:
            return f"Error: Permission denied"
        except Exception as e:
            return f"Error listing directory"
