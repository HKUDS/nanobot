"""File system tools: read, write, edit."""

import difflib
import os
import re
from io import StringIO
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from nanobot.agent.tools.base import Tool, ToolResult


def _resolve_path(
    path: str, workspace: Path | None = None, allowed_dir: Path | None = None
) -> Path:
    """Resolve path against workspace (if relative) and enforce directory restriction."""
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


class ReadFileTool(Tool):
    """Tool to read file contents."""

    _MAX_CHARS = 128_000  # ~128 KB — prevents OOM from reading huge files into LLM context

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
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
            "properties": {"path": {"type": "string", "description": "The file path to read"}},
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"
            if not file_path.is_file():
                return f"Error: Not a file: {path}"

            size = file_path.stat().st_size
            if size > self._MAX_CHARS * 4:  # rough upper bound (UTF-8 chars ≤ 4 bytes)
                return (
                    f"Error: File too large ({size:,} bytes). "
                    f"Use exec tool with head/tail/grep to read portions."
                )

            content = file_path.read_text(encoding="utf-8")
            if len(content) > self._MAX_CHARS:
                return content[: self._MAX_CHARS] + f"\n\n... (truncated — file is {len(content):,} chars, limit {self._MAX_CHARS:,})"
            return content
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {str(e)}"


class WriteFileTool(Tool):
    """Tool to write content to a file."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
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
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str | ToolResult:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            # Generate content preview for user display
            preview = self._format_content_preview(content, str(file_path))

            return ToolResult(
                content=f"Successfully wrote {len(content)} bytes to {file_path}",
                display=preview,
                display_type="write_preview",
            )
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {str(e)}"

    def _format_content_preview(self, content: str, path: str, max_lines: int = 20) -> str:
        """
        Format a preview of written file content.

        Args:
            content: The content that was written.
            path: File path for display.
            max_lines: Maximum number of lines to preview.

        Returns:
            Formatted preview string.
        """
        lines = content.splitlines(keepends=False)
        total_lines = len(lines)

        preview = []
        preview.append(f"Wrote {len(content)} bytes to {path}")

        if total_lines == 0:
            preview.append("(empty file)")
        elif total_lines <= max_lines:
            # Show all content with line numbers
            for i, line in enumerate(lines, 1):
                preview.append(f" {i:>4}   {line}")
        else:
            # Show first max_lines with indicator
            preview.append(f"--- Content preview (first {max_lines} of {total_lines} lines) ---")
            for i in range(max_lines):
                preview.append(f" {i+1:>4}   {lines[i]}")
            preview.append(f"... ({total_lines - max_lines} more lines)")

        return "\n".join(preview) + "\n"


class EditFileTool(Tool):
    """Tool to edit a file by replacing text."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
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
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "The exact text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace with"},
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str | ToolResult:
        try:
            file_path = _resolve_path(path, self._workspace, self._allowed_dir)
            if not file_path.exists():
                return f"Error: File not found: {path}"

            content = file_path.read_text(encoding="utf-8")

            if old_text not in content:
                return self._not_found_message(old_text, content, path)

            # Count occurrences
            count = content.count(old_text)
            if count > 1:
                return f"Warning: old_text appears {count} times. Please provide more context to make it unique."

            old_lines = content.splitlines(keepends=True)
            new_content = content.replace(old_text, new_text, 1)
            new_lines = new_content.splitlines(keepends=True)
            file_path.write_text(new_content, encoding="utf-8")

            # Generate colored diff for user display
            diff_display = self._format_colored_diff(old_lines, new_lines, str(file_path))

            return ToolResult(
                content=f"Successfully edited {file_path}",
                display=diff_display,
                display_type="diff",
            )
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {str(e)}"

    def _format_colored_diff(self, old_lines: list[str], new_lines: list[str], path: str) -> str:
        """
        Format diff with ANSI colors for terminal display.

        Format:
        - Line numbers on left (colored: red for removed, green for added)
        - + for added lines (green background)
        - - for removed lines (red background)
        - Space for unchanged lines (no color)
        - Background colors extend to full terminal width

        Args:
            old_lines: Original file lines.
            new_lines: Modified file lines.
            path: File path for display.

        Returns:
            Formatted diff string with ANSI color codes.
        """
        # ANSI color codes - using very dark background colors
        RESET = "\x1b[0m"
        # Very dark red background (RGB: 50, 0, 0) for removed lines
        RED_BG = "\x1b[48;2;50;0;0m"
        # Very dark green background (RGB: 0, 50, 0) for added lines
        GREEN_BG = "\x1b[48;2;0;50;0m"
        # Red foreground for line numbers (removed lines)
        RED_FG = "\x1b[38;2;255;100;100m"
        # Green foreground for line numbers (added lines)
        GREEN_FG = "\x1b[38;2;100;255;100m"
        BOLD = "\x1b[1m"  # Bold for header

        # Get terminal width for full-line background
        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            # Fallback if terminal size cannot be determined
            terminal_width = 100

        # Generate unified diff
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))

        if not diff:
            return "No changes to display\n"

        # Count added and removed lines
        added_count = sum(1 for line in diff if line.startswith("+"))
        removed_count = sum(1 for line in diff if line.startswith("-"))

        lines = []
        lines.append(f"{BOLD}Update: {path}{RESET}\n")
        lines.append(f"  ↳ Added {added_count} line{'s' if added_count != 1 else ''}, removed {removed_count} line{'s' if removed_count != 1 else ''}\n")

        # Track line numbers for old and new files
        old_line_num = 0
        new_line_num = 0

        for line in diff:
            if line.startswith("@@"):
                # Parse hunk header to get line numbers, but don't display it
                # Format: @@ -old_start,old_count +new_start,new_count @@
                match = re.search(r"-(\d+)", line)
                if match:
                    old_line_num = int(match.group(1))  # Current position in old file
                match = re.search(r"\+(\d+)", line)
                if match:
                    new_line_num = int(match.group(1))  # Current position in new file
                # Skip the @@ header line
            elif line.startswith("---") or line.startswith("+++"):
                # Skip file header lines
                continue
            elif line.startswith("-"):
                # Removed line - show with old line number and red background
                # The old_line_num represents the line number in the original file
                content = line[1:].rstrip("\n")
                visible_prefix = f" {old_line_num:>4} - {content}"
                remaining = max(0, terminal_width - len(visible_prefix))
                lines.append(f"{RED_BG} {RED_FG}{old_line_num:>4}{RESET}{RED_BG} - {content}{' ' * remaining}{RESET}\n")
                # Move to next line in old file after displaying
                old_line_num += 1
            elif line.startswith("+"):
                # Added line - show with new line number and green background
                # The new_line_num represents the line number in the new file
                content = line[1:].rstrip("\n")
                visible_prefix = f" {new_line_num:>4} + {content}"
                remaining = max(0, terminal_width - len(visible_prefix))
                lines.append(f"{GREEN_BG} {GREEN_FG}{new_line_num:>4}{RESET}{GREEN_BG} + {content}{' ' * remaining}{RESET}\n")
                # Move to next line in new file after displaying
                new_line_num += 1
            elif line.startswith(" "):
                # Unchanged line - exists in both files
                # Show new_line_num since we're viewing the modified file
                content = line[1:].rstrip("\n")
                lines.append(f" {new_line_num:>4}   {content}\n")
                # Move to next line in both files
                old_line_num += 1
                new_line_num += 1

        return "".join(lines)

    @staticmethod
    def _not_found_message(old_text: str, content: str, path: str) -> str:
        """Build a helpful error when old_text is not found."""
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)

        best_ratio, best_start = 0.0, 0
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        if best_ratio > 0.5:
            diff = "\n".join(
                difflib.unified_diff(
                    old_lines,
                    lines[best_start : best_start + window],
                    fromfile="old_text (provided)",
                    tofile=f"{path} (actual, line {best_start + 1})",
                    lineterm="",
                )
            )
            return f"Error: old_text not found in {path}.\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
        return (
            f"Error: old_text not found in {path}. No similar text found. Verify the file content."
        )


class ListDirTool(Tool):
    """Tool to list directory contents."""

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        self._workspace = workspace
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
            "properties": {"path": {"type": "string", "description": "The directory path to list"}},
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs: Any) -> str:
        try:
            dir_path = _resolve_path(path, self._workspace, self._allowed_dir)
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
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {str(e)}"
