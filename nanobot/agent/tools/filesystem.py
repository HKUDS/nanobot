"""File system tools: read, write, edit."""

import difflib
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


def _resolve_path(path: str, allowed_dir: Path | None = None) -> Path:
    """Resolve path and optionally enforce directory restriction."""
    resolved = Path(path).expanduser().resolve()
    if allowed_dir and not str(resolved).startswith(str(allowed_dir.resolve())):
        raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


def _find_best_match(content: str, old_text: str, max_context: int = 5) -> str:
    """Find the closest matching region in content and return a helpful diff."""
    old_lines = old_text.splitlines(keepends=True)
    content_lines = content.splitlines(keepends=True)

    if not old_lines or not content_lines:
        return ""

    # Use SequenceMatcher to find the best matching block
    matcher = difflib.SequenceMatcher(None, content_lines, old_lines)
    best = matcher.find_longest_match(0, len(content_lines), 0, len(old_lines))

    if best.size == 0:
        # No matching lines at all — show the first few lines of the file
        preview = content_lines[:max_context]
        return (
            f"No matching lines found. File starts with:\n"
            + "".join(f"  {i + 1}: {line}" for i, line in enumerate(preview))
        )

    # Show a window around the best match
    start = max(0, best.a - max_context)
    end = min(len(content_lines), best.a + best.size + max_context)
    region = content_lines[start:end]

    diff = difflib.unified_diff(
        region,
        old_lines,
        fromfile="file (closest region)",
        tofile="old_text (your input)",
        lineterm="",
    )
    diff_text = "\n".join(list(diff)[:30])  # Cap at 30 lines

    hints = []
    # Check for trailing whitespace differences
    for i, (a, b) in enumerate(zip(content_lines[best.a:], old_lines)):
        if a.rstrip() == b.rstrip() and a != b:
            hints.append(f"Line {best.a + i + 1}: trailing whitespace differs")
            break
    # Check for line ending differences
    if "\r\n" in content and "\r\n" not in old_text:
        hints.append("File uses CRLF line endings but old_text uses LF")
    elif "\r\n" not in content and "\r\n" in old_text:
        hints.append("File uses LF line endings but old_text uses CRLF")

    parts = [f"Closest match near line {best.a + 1}:"]
    if diff_text:
        parts.append(diff_text)
    if hints:
        parts.append("Hints: " + "; ".join(hints))

    return "\n".join(parts)


class ReadFileTool(Tool):
    """Tool to read file contents."""

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

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
                    "description": "The file path to read",
                }
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            content = file_path.read_text(encoding="utf-8")
            return content
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

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
                    "description": "The file path to write to",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

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
                    "description": "The file path to edit",
                },
                "old_text": {
                    "type": "string",
                    "description": "The exact text to find and replace",
                },
                "new_text": {
                    "type": "string",
                    "description": "The text to replace with",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                detail = _find_best_match(content, old_text)
                old_line_count = len(old_text.splitlines())
                file_line_count = len(content.splitlines())
                return (
                    f"Error: old_text not found in {path}.\n"
                    f"old_text has {old_line_count} lines; "
                    f"file has {file_line_count} lines.\n"
                    f"{detail}"
                )

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return (
                    f"Warning: old_text appears {count} times in {path}. "
                    f"Please provide more surrounding context to make the match unique."
                )

            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")

            return f"Successfully edited {path}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"


class ListDirTool(Tool):
    """Tool to list directory contents."""

    def __init__(self, allowed_dir: Path | None = None):
        self._allowed_dir = allowed_dir

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
                    "description": "The directory path to list",
                }
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = _resolve_path(path, self._allowed_dir)
            if not dir_path.exists():
                return f"Error: Directory not found: {path}"
            if not dir_path.is_dir():
                return f"Error: Not a directory: {path}"

            items = []
            for item in sorted(dir_path.iterdir()):
                prefix = "\U0001f4c1 " if item.is_dir() else "\U0001f4c4 "
                items.append(f"{prefix}{item.name}")

            if not items:
                return f"Directory {path} is empty"

            return "\n".join(items)
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
