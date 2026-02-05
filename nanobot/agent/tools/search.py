"""Search tools for codebase navigation."""

import re
from itertools import islice
from pathlib import Path
from typing import Any, Optional

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.filesystem import validate_workspace_path, WorkspaceSecurityError

# Security and performance constants
MAX_GLOB_RESULTS = 100
MAX_GREP_RESULTS = 50
MAX_FILES_TO_SCAN = 1000
MAX_PATTERN_LENGTH = 1000
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class GlobTool(Tool):
    """Find files matching a glob pattern within workspace."""

    def __init__(
        self,
        workspace: Optional[Path] = None,
        restrict_to_workspace: bool = True,
    ):
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return "Find files matching a glob pattern (e.g., '**/*.py', 'src/**/*.ts')"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files (e.g., '**/*.py')",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (defaults to workspace root)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, path: str = "", **kwargs: Any) -> str:
        try:
            # Determine search root
            if path:
                search_root = validate_workspace_path(
                    path, self.workspace, self.restrict_to_workspace
                )
            elif self.workspace:
                search_root = self.workspace.resolve()
            else:
                search_root = Path.cwd()

            if not search_root.is_dir():
                return f"Error: Not a directory: {search_root}"

            # Find matching files with enumeration limit and symlink filtering (HIGH-2, CRIT-2)
            matches_iter = search_root.glob(pattern)
            matches = []
            for m in matches_iter:
                if not m.is_symlink():  # Skip symlinks for security (CRIT-2)
                    matches.append(m)
                if len(matches) >= MAX_GLOB_RESULTS * 2:  # Limit enumeration (HIGH-2)
                    break
            matches = sorted(matches)

            # Filter to only files within workspace
            if self.restrict_to_workspace and self.workspace:
                workspace_resolved = self.workspace.resolve()
                matches = [
                    m for m in matches
                    if m.resolve().is_relative_to(workspace_resolved)
                ]

            if not matches:
                return f"No files found matching '{pattern}'"

            # Format results (limit to MAX_GLOB_RESULTS files)
            results = []
            for m in matches[:MAX_GLOB_RESULTS]:
                if path:
                    try:
                        rel_path = m.relative_to(search_root)
                    except ValueError:
                        rel_path = m
                else:
                    rel_path = m
                results.append(str(rel_path))

            output = "\n".join(results)
            if len(matches) > MAX_GLOB_RESULTS:
                output += f"\n... and {len(matches) - MAX_GLOB_RESULTS} more files"

            return output

        except WorkspaceSecurityError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error searching files: {e}"


class GrepTool(Tool):
    """Search file contents using regex patterns."""

    def __init__(
        self,
        workspace: Optional[Path] = None,
        restrict_to_workspace: bool = True,
    ):
        self.workspace = workspace
        self.restrict_to_workspace = restrict_to_workspace

    def _compile_pattern_safe(self, pattern: str, case_insensitive: bool) -> re.Pattern:
        """Compile regex pattern with safety checks (CRIT-1: ReDoS prevention)."""
        if len(pattern) > MAX_PATTERN_LENGTH:
            raise ValueError(f"Pattern too long (max {MAX_PATTERN_LENGTH} characters)")

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            return re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped (binary or too large) (HIGH-3)."""
        try:
            # Skip large files
            if file_path.stat().st_size > MAX_FILE_SIZE:
                return True
            # Quick binary check - null bytes indicate binary
            with open(file_path, 'rb') as f:
                chunk = f.read(1024)
                if b'\x00' in chunk:
                    return True
            return False
        except Exception:
            return True

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "Search for a regex pattern in files. Returns matching lines with file paths and line numbers."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search (defaults to workspace)",
                },
                "glob": {
                    "type": "string",
                    "description": "File pattern filter (e.g., '*.py'). Only used when path is a directory.",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Ignore case when matching (default: false)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(
        self,
        pattern: str,
        path: str = "",
        glob: str = "*",
        case_insensitive: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            # Compile regex with safety checks (CRIT-1)
            try:
                regex = self._compile_pattern_safe(pattern, case_insensitive)
            except ValueError as e:
                return f"Error: {e}"

            # Determine search root
            if path:
                search_path = validate_workspace_path(
                    path, self.workspace, self.restrict_to_workspace
                )
            elif self.workspace:
                search_path = self.workspace.resolve()
            else:
                search_path = Path.cwd()

            # Collect files to search with enumeration limit (HIGH-1)
            if search_path.is_file():
                files = [search_path]
            elif search_path.is_dir():
                # Limit file enumeration and filter symlinks
                files = []
                for f in search_path.rglob(glob):
                    if f.is_file() and not f.is_symlink():
                        files.append(f)
                        if len(files) >= MAX_FILES_TO_SCAN:
                            break
                files = sorted(files)
            else:
                return f"Error: Path not found: {search_path}"

            # Filter to workspace
            if self.restrict_to_workspace and self.workspace:
                workspace_resolved = self.workspace.resolve()
                files = [
                    f for f in files
                    if f.resolve().is_relative_to(workspace_resolved)
                ]

            # Search files
            results = []

            for file_path in files:
                if len(results) >= MAX_GREP_RESULTS:
                    break

                # Skip binary and large files (HIGH-3)
                if self._should_skip_file(file_path):
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    lines = content.splitlines()

                    for line_num, line in enumerate(lines, 1):
                        if len(results) >= MAX_GREP_RESULTS:
                            break
                        if regex.search(line):
                            if path:
                                try:
                                    rel_path = file_path.relative_to(search_path)
                                except ValueError:
                                    rel_path = file_path
                            else:
                                rel_path = file_path
                            results.append(f"{rel_path}:{line_num}: {line.strip()}")

                except (PermissionError, IsADirectoryError):
                    continue

            if not results:
                return f"No matches found for pattern '{pattern}'"

            output = "\n".join(results)
            if len(results) >= MAX_GREP_RESULTS:
                output += f"\n... (limited to {MAX_GREP_RESULTS} results)"

            return output

        except WorkspaceSecurityError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error searching: {e}"
