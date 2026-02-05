"""File system tools: read, write, edit."""

import shutil
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


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
        try:
            file_path = Path(path).expanduser()
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"
            
            content = file_path.read_text(encoding="utf-8")
            return content
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


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
        try:
            file_path = Path(path).expanduser()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


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
        try:
            file_path = Path(path).expanduser()
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
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


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
        try:
            dir_path = Path(path).expanduser()
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
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"


class RenameFileTool(Tool):
    """Tool to rename a file or directory."""

    @property
    def name(self) -> str:
        return "rename_file"

    @property
    def description(self) -> str:
        return "Rename a file or directory to a new name in the same location."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "old_path": {
                    "type": "string",
                    "description": "The current path of the file or directory"
                },
                "new_name": {
                    "type": "string",
                    "description": "The new name (not full path, just the name)"
                }
            },
            "required": ["old_path", "new_name"]
        }

    async def execute(self, old_path: str, new_name: str, **kwargs: Any) -> str:
        try:
            old_file = Path(old_path).expanduser()
            if not old_file.exists():
                return f"Error: File or directory not found: {old_path}"

            # Ensure new_name is just a name, not a path
            if "/" in new_name or "\\" in new_name:
                return "Error: new_name should be just a name, not a path"

            new_file = old_file.parent / new_name
            if new_file.exists():
                return f"Error: Target already exists: {new_file}"

            old_file.rename(new_file)
            return f"Successfully renamed {old_path} to {new_name}"
        except PermissionError:
            return f"Error: Permission denied"
        except Exception as e:
            return f"Error renaming: {str(e)}"


class MoveFileTool(Tool):
    """Tool to move a file or directory to a new location."""

    @property
    def name(self) -> str:
        return "move_file"

    @property
    def description(self) -> str:
        return "Move a file or directory to a new location. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The source path to move"
                },
                "destination": {
                    "type": "string",
                    "description": "The destination path"
                }
            },
            "required": ["source", "destination"]
        }

    async def execute(self, source: str, destination: str, **kwargs: Any) -> str:
        try:
            src_path = Path(source).expanduser()
            if not src_path.exists():
                return f"Error: Source not found: {source}"

            dest_path = Path(destination).expanduser()

            # If destination is a directory, move source into it
            if dest_path.is_dir():
                dest_path = dest_path / src_path.name

            # Create parent directories if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if dest_path.exists():
                return f"Error: Destination already exists: {destination}"

            shutil.move(str(src_path), str(dest_path))
            return f"Successfully moved {source} to {destination}"
        except PermissionError:
            return f"Error: Permission denied"
        except Exception as e:
            return f"Error moving: {str(e)}"


class CopyFileTool(Tool):
    """Tool to copy a file or directory."""

    @property
    def name(self) -> str:
        return "copy_file"

    @property
    def description(self) -> str:
        return "Copy a file or directory to a new location. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "The source path to copy"
                },
                "destination": {
                    "type": "string",
                    "description": "The destination path"
                }
            },
            "required": ["source", "destination"]
        }

    async def execute(self, source: str, destination: str, **kwargs: Any) -> str:
        try:
            src_path = Path(source).expanduser()
            if not src_path.exists():
                return f"Error: Source not found: {source}"

            dest_path = Path(destination).expanduser()

            # If destination is a directory, copy source into it
            if dest_path.is_dir():
                dest_path = dest_path / src_path.name

            # Create parent directories if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if dest_path.exists():
                return f"Error: Destination already exists: {destination}"

            if src_path.is_dir():
                shutil.copytree(str(src_path), str(dest_path))
            else:
                shutil.copy2(str(src_path), str(dest_path))

            return f"Successfully copied {source} to {destination}"
        except PermissionError:
            return f"Error: Permission denied"
        except Exception as e:
            return f"Error copying: {str(e)}"


class CreateDirTool(Tool):
    """Tool to create a new directory."""

    @property
    def name(self) -> str:
        return "create_dir"

    @property
    def description(self) -> str:
        return "Create a new directory. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The directory path to create"
                }
            },
            "required": ["path"]
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = Path(path).expanduser()
            if dir_path.exists():
                if dir_path.is_dir():
                    return f"Directory already exists: {path}"
                else:
                    return f"Error: A file with this name already exists: {path}"

            dir_path.mkdir(parents=True, exist_ok=True)
            return f"Successfully created directory: {path}"
        except PermissionError:
            return f"Error: Permission denied: {path}"
        except Exception as e:
            return f"Error creating directory: {str(e)}"
