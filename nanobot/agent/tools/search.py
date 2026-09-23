"""Search tools: file discovery and grep."""

# pyright: reportIncompatibleMethodOverride=false, reportPrivateUsage=false

from __future__ import annotations

import asyncio
import fnmatch
import heapq
import os
import re
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, TypeVar

from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.filesystem import ListDirTool, _FsTool
from nanobot.utils.document import (
    LocatedDocumentLine,
    PdfPageRangeError,
    open_document_line_source,
)

_DEFAULT_HEAD_LIMIT = 250
_DEFAULT_FILE_HEAD_LIMIT = 200
_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".pptx"})
T = TypeVar("T")
_TYPE_GLOB_MAP = {
    "py": ("*.py", "*.pyi"),
    "python": ("*.py", "*.pyi"),
    "js": ("*.js", "*.jsx", "*.mjs", "*.cjs"),
    "ts": ("*.ts", "*.tsx", "*.mts", "*.cts"),
    "tsx": ("*.tsx",),
    "jsx": ("*.jsx",),
    "json": ("*.json",),
    "md": ("*.md", "*.mdx"),
    "markdown": ("*.md", "*.mdx"),
    "go": ("*.go",),
    "rs": ("*.rs",),
    "rust": ("*.rs",),
    "java": ("*.java",),
    "sh": ("*.sh", "*.bash"),
    "yaml": ("*.yaml", "*.yml"),
    "yml": ("*.yaml", "*.yml"),
    "toml": ("*.toml",),
    "sql": ("*.sql",),
    "html": ("*.html", "*.htm"),
    "css": ("*.css", "*.scss", "*.sass"),
}


@dataclass(slots=True)
class _PendingContextMatch:
    lines: list[LocatedDocumentLine]
    match_index: int
    match_start: int
    remaining_after: int


@dataclass(slots=True)
class _FindFilesEntry:
    path: Path
    rel_path: str
    display_path: str
    name: str
    is_dir: bool


class _SearchCancelledError(Exception):
    """Stop a worker scan after its owning async task was cancelled."""


class _SearchBudgetExceededError(Exception):
    """Stop an unbounded filesystem scan at its configured budget."""


@dataclass(slots=True)
class _SearchBudget:
    cancelled: threading.Event
    deadline: float
    max_paths: int
    scanned_paths: int = 0

    def checkpoint(self) -> None:
        if self.cancelled.is_set():
            raise _SearchCancelledError
        if time.monotonic() >= self.deadline:
            raise _SearchBudgetExceededError("time")

    def visit_path(self) -> None:
        self.checkpoint()
        self.scanned_paths += 1
        if self.scanned_paths > self.max_paths:
            raise _SearchBudgetExceededError("paths")


def _normalize_pattern(pattern: str) -> str:
    return pattern.strip().replace("\\", "/")


@lru_cache(maxsize=128)
def _glob_patterns(pattern: str) -> tuple[str, ...]:
    """Expand bounded brace alternatives before matching path segments."""
    pending = [_normalize_pattern(pattern)]
    expanded: list[str] = []
    while pending:
        current = pending.pop()
        braces = re.search(r"\{([^{}]*)\}", current)
        if braces is None:
            if "{" in current or "}" in current:
                raise ValueError("Invalid glob: unbalanced braces")
            expanded.append(current)
            continue
        options = braces[1].split(",")
        if len(options) < 2:
            raise ValueError("Invalid glob: braces require comma-separated alternatives")
        if len(expanded) + len(pending) + len(options) > 64:
            raise ValueError("Invalid glob: at most 64 brace alternatives are supported")
        pending.extend(current[:braces.start()] + part + current[braces.end():] for part in options)
    return tuple(expanded)


def _match_glob(rel_path: str, name: str, pattern: str) -> bool:
    return any(_match_path_glob(rel_path, name, item) for item in _glob_patterns(pattern))


def _match_path_glob(rel_path: str, name: str, normalized: str) -> bool:
    if not normalized:
        return False
    if "/" in normalized:
        pattern_parts = PurePosixPath(normalized).parts
        path_parts = PurePosixPath(rel_path).parts
        matched = [True] + [False] * len(path_parts)
        for part in pattern_parts:
            if part == "**":
                # A globstar consumes zero or more complete path segments.
                for index in range(1, len(matched)):
                    matched[index] = matched[index] or matched[index - 1]
            else:
                matched = [False] + [
                    matched[index] and fnmatch.fnmatchcase(path_part, part)
                    for index, path_part in enumerate(path_parts)
                ]
        return matched[-1]
    return fnmatch.fnmatch(name, normalized)


def _is_binary(raw: bytes) -> bool:
    if b"\x00" in raw:
        return True
    sample = raw[:4096]
    if not sample:
        return False
    non_text = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return (non_text / len(sample)) > 0.2


def _excel_column(index: int) -> str:
    """Return a 1-indexed spreadsheet column label without importing openpyxl."""
    label = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


def _paginate(items: list[T], limit: int | None, offset: int) -> tuple[list[T], bool]:
    if limit is None:
        return items[offset:], False
    sliced = items[offset : offset + limit]
    truncated = len(items) > offset + limit
    return sliced, truncated


def _text_page(
    items: list[str], limit: int | None, offset: int, max_chars: int,
) -> tuple[list[str], bool]:
    page, truncated = _paginate(items, limit, offset)
    size = 0
    for index, item in enumerate(page):
        size += len(item) + (1 if index else 0)
        if size > max_chars:
            if index == 0:
                raise ValueError("Search entry exceeds output budget; narrow the search path")
            return page[:index], True
    return page, truncated


def _pagination_note(limit: int | None, offset: int, truncated: bool) -> str | None:
    if truncated:
        if limit is None:
            return f"(pagination: offset={offset})"
        return f"(pagination: limit={limit}, offset={offset})"
    if offset > 0:
        return f"(pagination: offset={offset})"
    return None


def _matches_type(name: str, file_type: str | None) -> bool:
    if not file_type:
        return True
    lowered = file_type.strip().lower()
    if not lowered:
        return True
    patterns = _TYPE_GLOB_MAP.get(lowered, (f"*.{lowered}",))
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in patterns)


def _matches_query(rel_path: str, query: str | None) -> bool:
    if not query:
        return True
    haystack = rel_path.lower()
    terms = [part for part in query.lower().split() if part]
    return all(term in haystack for term in terms)


class _SearchTool(_FsTool):
    _IGNORE_DIRS = ListDirTool._IGNORE_DIRS | {".worktrees", ".worktree", ".nanobot"}
    _MAX_SCAN_PATHS = 500_000
    _MAX_SCAN_SECONDS = 30.0
    _MAX_RESULT_CHARS = 12_000

    @classmethod
    def _ignore_directory(cls, name: str) -> bool:
        return name in cls._IGNORE_DIRS or name.startswith(".verify-")

    def _display_path(self, target: Path, root: Path) -> str:
        workspace = self._display_workspace()
        if workspace:
            with suppress(ValueError):
                return target.relative_to(workspace).as_posix()
        return target.relative_to(root).as_posix()

    def _iter_files(self, root: Path, budget: _SearchBudget) -> Iterable[Path]:
        if root.is_file():
            budget.visit_path()
            yield root
            return

        for dirpath, dirnames, filenames in os.walk(root):
            budget.checkpoint()
            for _ in dirnames:
                budget.visit_path()
            dirnames[:] = sorted(d for d in dirnames if not self._ignore_directory(d))
            current = Path(dirpath)
            for filename in sorted(filenames):
                budget.visit_path()
                yield current / filename


class FindFilesTool(_SearchTool):
    """Find files by path fragment, glob, or type."""
    _scopes = {"core", "subagent"}

    @property
    def name(self) -> str:
        return "find_files"

    @property
    def description(self) -> str:
        return (
            "Find workspace paths by name, glob, or file type. "
            "Returns relative paths; skips dependencies, builds, worktrees and tool artifacts."
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Search root (default '.'); set path explicitly to search skipped worktrees, builds or tool artifacts",
                },
                "query": {
                    "type": "string",
                    "description": "Case-insensitive path terms; all must match",
                },
                "glob": {
                    "type": "string",
                    "description": "Root-relative path glob, e.g. 'src/**/*.{ts,tsx}'; bare '*.py' matches any depth",
                },
                "type": {
                    "type": "string",
                    "description": "File type, e.g. 'py', 'ts', 'md', or 'json'",
                },
                "include_dirs": {
                    "type": "boolean",
                    "description": "Include directories (default false)",
                },
                "sort": {
                    "type": "string",
                    "enum": ["path", "modified"],
                    "description": "Sort order (default path)",
                },
                "head_limit": {
                    "type": "integer",
                    "description": "Maximum paths (default 200; 0 for all)",
                    "minimum": 0,
                    "maximum": 1000,
                },
                "offset": {
                    "type": "integer",
                    "description": "Paths to skip before head_limit",
                    "minimum": 0,
                    "maximum": 100000,
                },
            },
        }

    def _entry(self, path: Path, root: Path, *, is_dir: bool) -> _FindFilesEntry:
        display_path = self._display_path(path, root)
        return _FindFilesEntry(
            path=path,
            rel_path=path.relative_to(root).as_posix(),
            display_path=display_path,
            name=path.name,
            is_dir=is_dir,
        )

    def _push_directory_entries(
        self,
        directory: Path,
        root: Path,
        frontier: list[tuple[str, int, _FindFilesEntry]],
        sequence: int,
        budget: _SearchBudget,
    ) -> int:
        budget.checkpoint()
        try:
            with os.scandir(directory) as entries:
                for raw_entry in entries:
                    budget.visit_path()
                    try:
                        is_dir = raw_entry.is_dir(follow_symlinks=False)
                        # os.walk yields special files and broken file symlinks,
                        # but does not descend into directory symlinks by default.
                        if not is_dir and raw_entry.is_symlink() and raw_entry.is_dir():
                            continue
                    except OSError:
                        continue
                    if is_dir and self._ignore_directory(raw_entry.name):
                        continue

                    entry = self._entry(Path(raw_entry.path), root, is_dir=is_dir)
                    sort_path = entry.display_path + ("/" if is_dir else "")
                    heapq.heappush(frontier, (sort_path, sequence, entry))
                    sequence += 1
        except OSError:
            # os.walk silently skips directories that cannot be listed. Preserve
            # that behavior while still allowing cancellation and budget errors
            # to propagate from the explicit checkpoints above.
            pass
        return sequence

    def _iter_paths(
        self,
        root: Path,
        *,
        include_dirs: bool,
        budget: _SearchBudget,
    ) -> Iterable[_FindFilesEntry]:
        budget.checkpoint()
        if root.is_file():
            budget.visit_path()
            yield self._entry(root, root.parent, is_dir=False)
            return

        if include_dirs:
            yield self._entry(root, root, is_dir=True)

        frontier: list[tuple[str, int, _FindFilesEntry]] = []
        sequence = self._push_directory_entries(root, root, frontier, 0, budget)
        while frontier:
            budget.checkpoint()
            _, _, entry = heapq.heappop(frontier)
            if entry.is_dir:
                if include_dirs:
                    yield entry
                sequence = self._push_directory_entries(
                    entry.path,
                    root,
                    frontier,
                    sequence,
                    budget,
                )
            else:
                yield entry

    @staticmethod
    def _matches_entry(
        entry: _FindFilesEntry,
        *,
        query: str | None,
        glob: str | None,
        file_type: str | None,
    ) -> bool:
        if glob and not _match_glob(entry.rel_path, entry.name, glob):
            return False
        if entry.is_dir:
            if file_type:
                return False
        elif not _matches_type(entry.name, file_type):
            return False
        return _matches_query(entry.display_path, query)

    async def execute(
        self,
        path: str = ".",
        query: str | None = None,
        glob: str | None = None,
        type: str | None = None,
        include_dirs: bool = False,
        sort: str = "path",
        head_limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> str:
        cancelled = threading.Event()
        try:
            return await asyncio.to_thread(
                self._execute_sync,
                path=path,
                query=query,
                glob=glob,
                file_type=type,
                include_dirs=include_dirs,
                sort=sort,
                head_limit=head_limit,
                offset=offset,
                cancelled=cancelled,
            )
        except asyncio.CancelledError:
            cancelled.set()
            raise
        except PermissionError as e:
            return ToolResult.error(f"Error: {e}")
        except Exception as e:
            return ToolResult.error(f"Error finding files: {e}")

    def _execute_sync(
        self,
        *,
        path: str,
        query: str | None,
        glob: str | None,
        file_type: str | None,
        include_dirs: bool,
        sort: str,
        head_limit: int | None,
        offset: int,
        cancelled: threading.Event,
    ) -> str:
        started_at = time.monotonic()
        if cancelled.is_set():
            raise _SearchCancelledError
        target = self._resolve(path or ".")
        if not target.exists():
            return ToolResult.error(f"Error: Path not found: {path}")
        if not (target.is_dir() or target.is_file()):
            return ToolResult.error(f"Error: Unsupported path: {path}")

        if glob:
            _glob_patterns(glob)

        if sort not in {"path", "modified"}:
            return ToolResult.error("Error: sort must be 'path' or 'modified'")

        limit = (
            _DEFAULT_FILE_HEAD_LIMIT
            if head_limit is None
            else None if head_limit == 0 else head_limit
        )
        budget = _SearchBudget(
            cancelled=cancelled,
            deadline=started_at + self._MAX_SCAN_SECONDS,
            max_paths=self._MAX_SCAN_PATHS,
        )

        def matching_entries() -> Iterator[tuple[str, float]]:
            for entry in self._iter_paths(
                target,
                include_dirs=include_dirs,
                budget=budget,
            ):
                if not self._matches_entry(
                    entry,
                    query=query,
                    glob=glob,
                    file_type=file_type,
                ):
                    continue
                mtime = 0.0
                if sort == "modified":
                    try:
                        mtime = entry.path.stat().st_mtime
                    except OSError:
                        pass
                suffix = "/" if entry.is_dir else ""
                yield entry.display_path + suffix, mtime

        matches: list[tuple[str, float]]
        try:
            if sort == "modified":
                if limit is None:
                    matches = sorted(matching_entries(), key=lambda item: (-item[1], item[0]))
                else:
                    selection_size = offset + limit + 1
                    matches = heapq.nsmallest(
                        selection_size,
                        matching_entries(),
                        key=lambda item: (-item[1], item[0]),
                    )
            else:
                selection_size = None if limit is None else offset + limit + 1
                matches = []
                for match in matching_entries():
                    matches.append(match)
                    if selection_size is not None and len(matches) >= selection_size:
                        break
            budget.checkpoint()
        except _SearchBudgetExceededError as exc:
            if str(exc) == "paths":
                detail = f"{self._MAX_SCAN_PATHS} paths"
            else:
                detail = f"{self._MAX_SCAN_SECONDS:g} seconds"
            return ToolResult.error(
                f"Error: find_files scan exceeded {detail}; "
                "narrow path, query, glob, or type and retry."
            )

        paths = [item[0] for item in matches]
        paged, truncated = _text_page(paths, limit, offset, self._MAX_RESULT_CHARS)
        if not paged:
            return "No files found"

        result = "\n".join(paged)
        note = _pagination_note(limit, offset, truncated)
        if note:
            result += "\n\n" + note
        if truncated:
            result += f"\n(use offset={offset + len(paged)} to continue)"
        return result


class GrepTool(_SearchTool):
    """Search text and document contents using a regex-like pattern."""
    _scopes = {"core", "subagent"}

    _MAX_RENDERED_LINE_CHARS = 2_000
    _MAX_FILE_BYTES = 2_000_000
    _MAX_EXPLICIT_FILE_BYTES = 100_000_000

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search text, PDF, DOCX, XLSX, and PPTX content. "
            "Returns matches with five context lines and source locators by default."
        )

    @property
    def read_only(self) -> bool:
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex, or literal text when fixed_strings=true",
                    "minLength": 1,
                },
                "path": {
                    "type": "string",
                    "description": "Search root (default '.'); set path explicitly to search skipped worktrees, builds or tool artifacts",
                },
                "glob": {
                    "type": "string",
                    "description": "Root-relative path glob, e.g. 'src/**/*.{ts,tsx}'; bare '*.py' matches any depth",
                },
                "type": {
                    "type": "string",
                    "description": "File type, e.g. 'py', 'ts', 'md', or 'json'",
                },
                "pages": {
                    "type": "string",
                    "description": "PDF page number or range, e.g. '7' or '101-200' (max 100 pages)",
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Ignore case (default false)",
                },
                "fixed_strings": {
                    "type": "boolean",
                    "description": "Treat pattern literally (default false)",
                },
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": (
                        "content: matches with context (default); "
                        "files_with_matches: paths; count: matches per file"
                    ),
                },
                "context_before": {
                    "type": "integer",
                    "description": "Context lines before a match (default 5)",
                    "minimum": 0,
                    "maximum": 20,
                },
                "context_after": {
                    "type": "integer",
                    "description": "Context lines after a match (default 5)",
                    "minimum": 0,
                    "maximum": 20,
                },
                "head_limit": {
                    "type": "integer",
                    "description": "Maximum matches or file entries (default 250; 0 for all)",
                    "minimum": 0,
                    "maximum": 1000,
                },
                "offset": {
                    "type": "integer",
                    "description": "Matches or file entries to skip before head_limit",
                    "minimum": 0,
                    "maximum": 100000,
                },
            },
            "required": ["pattern"],
        }

    @staticmethod
    def _clip_rendered_line(text: str, match_start: int | None = None) -> str:
        limit = GrepTool._MAX_RENDERED_LINE_CHARS
        if len(text) <= limit:
            return text

        marker = "..."
        available = limit - len(marker)
        if match_start is None:
            return text[:available] + marker

        start = max(0, match_start - available // 3)
        start = min(start, len(text) - available)
        end = start + available
        prefix = marker if start else ""
        suffix = marker if end < len(text) else ""
        visible = text[start:end]
        if prefix and suffix:
            visible = visible[: available - len(marker)]
        return prefix + visible + suffix

    @staticmethod
    def _matching_contexts(
        lines: Iterable[LocatedDocumentLine],
        regex: re.Pattern[str],
        before: int,
        after: int,
    ) -> Iterable[tuple[list[LocatedDocumentLine], int, int]]:
        history: deque[LocatedDocumentLine] = deque(maxlen=before)
        pending: list[_PendingContextMatch] = []

        for line in lines:
            if not line.searchable:
                continue

            still_pending: list[_PendingContextMatch] = []
            for item in pending:
                item.lines.append(line)
                item.remaining_after -= 1
                if item.remaining_after == 0:
                    yield item.lines, item.match_index, item.match_start
                else:
                    still_pending.append(item)
            pending = still_pending

            match = regex.search(line.text)
            if match is not None:
                context_lines = [*history, line]
                item = _PendingContextMatch(
                    lines=context_lines,
                    match_index=len(context_lines) - 1,
                    match_start=match.start(),
                    remaining_after=after,
                )
                if after == 0:
                    yield item.lines, item.match_index, item.match_start
                else:
                    pending.append(item)
            history.append(line)

        for item in pending:
            yield item.lines, item.match_index, item.match_start

    @staticmethod
    def _format_block(
        display_path: str,
        lines: list[LocatedDocumentLine],
        match_index: int,
        match_start: int = 0,
        matches: dict[int, int] | None = None,
    ) -> str:
        match_line = lines[match_index]
        source_line = match_line.extracted_line
        match_locator = match_line.locator
        if match_locator.startswith("sheet="):
            column = _excel_column(match_line.text[:match_start].count("\t") + 1)
            row_match = re.search(r",row=(\d+)$", match_locator)
            if row_match:
                match_locator += f",cell={column}{row_match.group(1)}"
        suffix = f" [{match_locator}]" if match_locator else ""
        block = [f"{display_path}:{source_line}{suffix}"]
        matches = matches if matches is not None else {source_line: match_start}
        for line in lines:
            is_match = line.extracted_line in matches
            marker = ">" if is_match else " "
            coordinate = str(line.extracted_line)
            if line.locator:
                coordinate += f" [{line.locator}]"
            rendered = GrepTool._clip_rendered_line(
                line.text,
                matches.get(line.extracted_line),
            )
            block.append(f"{marker} {coordinate}| {rendered}")
        return "\n".join(block)

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        type: str | None = None,
        pages: str | None = None,
        case_insensitive: bool = False,
        fixed_strings: bool = False,
        output_mode: str = "content",
        context_before: int = 5,
        context_after: int = 5,
        max_matches: int | None = None,
        max_results: int | None = None,
        head_limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> str:
        cancelled = threading.Event()
        try:
            return await asyncio.to_thread(
                self._execute_sync,
                pattern=pattern, path=path, glob=glob, type=type, pages=pages,
                case_insensitive=case_insensitive, fixed_strings=fixed_strings,
                output_mode=output_mode, context_before=context_before, context_after=context_after,
                max_matches=max_matches, max_results=max_results, head_limit=head_limit,
                offset=offset, cancelled=cancelled,
            )
        except asyncio.CancelledError:
            cancelled.set()
            raise

    def _execute_sync(
        self,
        *,
        pattern: str,
        path: str,
        glob: str | None,
        type: str | None,
        pages: str | None,
        case_insensitive: bool,
        fixed_strings: bool,
        output_mode: str,
        context_before: int,
        context_after: int,
        max_matches: int | None,
        max_results: int | None,
        head_limit: int | None,
        offset: int,
        cancelled: threading.Event,
    ) -> str:
        budget = _SearchBudget(
            cancelled=cancelled,
            deadline=time.monotonic() + self._MAX_SCAN_SECONDS,
            max_paths=self._MAX_SCAN_PATHS,
        )

        def checked_lines(lines: Iterable[LocatedDocumentLine]) -> Iterable[LocatedDocumentLine]:
            for line in lines:
                budget.checkpoint()
                yield line

        try:
            budget.checkpoint()
            if glob:
                _glob_patterns(glob)
            target = self._resolve(path or ".")
            if not target.exists():
                return ToolResult.error(f"Error: Path not found: {path}")
            if not (target.is_dir() or target.is_file()):
                return ToolResult.error(f"Error: Unsupported path: {path}")

            flags = re.IGNORECASE if case_insensitive else 0
            try:
                needle = re.escape(pattern) if fixed_strings else pattern
                regex = re.compile(needle, flags)
            except re.error as e:
                return ToolResult.error(f"Error: invalid regex pattern: {e}")

            if head_limit is not None:
                limit = None if head_limit == 0 else head_limit
            elif output_mode == "content" and max_matches is not None:
                limit = max_matches
            elif output_mode != "content" and max_results is not None:
                limit = max_results
            else:
                limit = _DEFAULT_HEAD_LIMIT
            blocks: list[str] = []
            result_chars = 0
            returned_matches = 0
            seen_content_matches = 0
            truncated = False
            size_truncated = False
            skipped_binary = 0
            skipped_large = 0
            document_errors: list[str] = []
            document_continuations: list[str] = []
            matching_files: list[str] = []
            paged: list[str] = []
            counts: dict[str, int] = {}
            file_mtimes: dict[str, float] = {}
            root = target if target.is_dir() else target.parent
            max_file_bytes = (
                self._MAX_EXPLICIT_FILE_BYTES if target.is_file() else self._MAX_FILE_BYTES
            )

            for file_path in self._iter_files(target, budget):
                rel_path = file_path.relative_to(root).as_posix()
                if glob and not _match_glob(rel_path, file_path.name, glob):
                    continue
                if not _matches_type(file_path.name, type):
                    continue
                display_path = self._display_path(file_path, root)

                try:
                    file_size = file_path.stat().st_size
                except OSError:
                    skipped_binary += 1
                    continue
                if file_size > max_file_bytes:
                    skipped_large += 1
                    continue
                try:
                    mtime = file_path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                source_iterator: Iterator[LocatedDocumentLine] | None = None
                is_document = file_path.suffix.lower() in _DOCUMENT_EXTENSIONS
                try:
                    if is_document:
                        source = open_document_line_source(file_path, pages=pages)
                        if source is None:
                            skipped_binary += 1
                            continue
                        source_iterator = source.lines
                        source_lines: Iterable[LocatedDocumentLine] = source_iterator
                        if source.continuation:
                            document_continuations.append(
                                f"({display_path}: continue PDF search with "
                                f"{source.continuation})"
                            )
                    else:
                        with file_path.open("rb") as file:
                            raw = file.read(max_file_bytes + 1)
                        if _is_binary(raw):
                            skipped_binary += 1
                            continue
                        try:
                            content = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            skipped_binary += 1
                            continue
                        source_lines = (
                            LocatedDocumentLine(text, line_no, "")
                            for line_no, text in enumerate(content.splitlines(), 1)
                        )

                    file_had_match = False
                    if output_mode == "content":
                        contexts = self._matching_contexts(
                            checked_lines(source_lines),
                            regex,
                            context_before,
                            context_after,
                        )
                        last_lines: list[LocatedDocumentLine] = []
                        last_matches: dict[int, int] = {}
                        for context_lines, match_index, match_start in contexts:
                            file_had_match = True
                            seen_content_matches += 1
                            if seen_content_matches <= offset:
                                continue
                            if limit is not None and returned_matches >= limit:
                                truncated = True
                                break
                            match_line = context_lines[match_index]
                            merge = bool(
                                last_lines
                                and context_lines[0].extracted_line <= last_lines[-1].extracted_line
                            )
                            if merge:
                                context_lines = last_lines + [
                                    line for line in context_lines
                                    if line.extracted_line > last_lines[-1].extracted_line
                                ]
                            matches = {
                                **(last_matches if merge else {}),
                                match_line.extracted_line: match_start,
                            }
                            first_match = next(iter(matches))
                            match_index = next(
                                index for index, line in enumerate(context_lines)
                                if line.extracted_line == first_match
                            )
                            block = self._format_block(
                                display_path,
                                context_lines,
                                match_index,
                                matches[first_match],
                                matches,
                            )
                            prior_chars = len(blocks[-1]) if merge else 0
                            extra_sep = 2 if blocks and not merge else 0
                            reduced_context = False
                            if result_chars - prior_chars + extra_sep + len(block) > self._MAX_RESULT_CHARS:
                                if not blocks:
                                    # A large context must still yield a match and advance pagination.
                                    context_lines = [match_line]
                                    block = self._format_block(display_path, context_lines, 0, match_start)
                                    reduced_context = True
                                    if len(block) > self._MAX_RESULT_CHARS:
                                        return ToolResult.error("Error: match exceeds output budget; narrow path or pattern")
                                else:
                                    size_truncated = True
                                    break
                            if merge:
                                blocks[-1] = block
                            else:
                                blocks.append(block)
                            result_chars += extra_sep + len(block) - prior_chars
                            returned_matches += 1
                            last_lines, last_matches = context_lines, matches
                            if reduced_context:
                                # Start a new page after falling back to a context-free match.
                                size_truncated = True
                                break
                    else:
                        for line in checked_lines(source_lines):
                            if not line.searchable or regex.search(line.text) is None:
                                continue
                            file_had_match = True
                            if output_mode == "count":
                                counts[display_path] = counts.get(display_path, 0) + 1
                                continue
                            if display_path not in matching_files:
                                matching_files.append(display_path)
                                file_mtimes[display_path] = mtime
                            break
                except (_SearchCancelledError, _SearchBudgetExceededError):
                    raise
                except Exception as e:
                    if not is_document:
                        raise
                    if target.is_file():
                        if isinstance(e, PdfPageRangeError):
                            return ToolResult.error(
                                f"Error: Invalid PDF page range '{pages}': {e!s}."
                            )
                        return ToolResult.error(
                            f"Error searching document {display_path}: {e!s}"
                        )
                    skipped_binary += 1
                    document_errors.append(f"{display_path}: {e!s}")
                    continue
                finally:
                    close = getattr(source_iterator, "close", None)
                    if close is not None:
                        close()
                if output_mode == "count" and file_had_match:
                    if display_path not in matching_files:
                        matching_files.append(display_path)
                        file_mtimes[display_path] = mtime
                if output_mode in {"count", "files_with_matches"} and file_had_match:
                    continue
                if truncated or size_truncated:
                    break

            if output_mode == "files_with_matches":
                if not matching_files:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    ordered_files = sorted(
                        matching_files,
                        key=lambda name: (-file_mtimes.get(name, 0.0), name),
                    )
                    paged, truncated = _text_page(ordered_files, limit, offset, self._MAX_RESULT_CHARS)
                    result = "\n".join(paged)
            elif output_mode == "count":
                if not counts:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    ordered_files = sorted(
                        matching_files,
                        key=lambda name: (-file_mtimes.get(name, 0.0), name),
                    )
                    count_lines = [f"{name}: {counts[name]}" for name in ordered_files]
                    paged, truncated = _text_page(count_lines, limit, offset, self._MAX_RESULT_CHARS)
                    result = "\n".join(paged)
            else:
                if not blocks:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    result = "\n\n".join(blocks)

            notes: list[str] = []
            if output_mode == "content" and truncated:
                notes.append(
                    f"(pagination: limit={limit}, offset={offset}; "
                    f"use offset={offset + returned_matches} to continue)"
                )
            elif output_mode == "content" and size_truncated:
                notes.append(
                    "(output truncated due to size; "
                    f"use offset={offset + returned_matches} to continue)"
                )
            elif truncated and output_mode in {"count", "files_with_matches"}:
                notes.append(
                    f"(pagination: limit={limit}, offset={offset}; "
                    f"use offset={offset + len(paged)} to continue)"
                )
            elif output_mode in {"count", "files_with_matches"} and offset > 0:
                notes.append(f"(pagination: offset={offset})")
            elif output_mode == "content" and offset > 0 and blocks:
                notes.append(f"(pagination: offset={offset})")
            if skipped_binary:
                notes.append(f"(skipped {skipped_binary} binary/unreadable files)")
            if skipped_large:
                notes.append(f"(skipped {skipped_large} large files)")
            if document_errors:
                notes.append(f"(first document error: {document_errors[0]})")
            notes.extend(document_continuations[:10])
            if output_mode == "count" and counts:
                notes.append(
                    f"(total matches: {sum(counts.values())} in {len(counts)} files)"
                )
            if notes:
                result += "\n\n" + "\n".join(notes)
            return result
        except _SearchBudgetExceededError as exc:
            detail = f"{self._MAX_SCAN_PATHS} paths" if str(exc) == "paths" else f"{self._MAX_SCAN_SECONDS:g} seconds"
            return ToolResult.error(f"Error: grep scan exceeded {detail}; narrow path, glob, or type and retry.")
        except PermissionError as e:
            return ToolResult.error(f"Error: {e}")
        except Exception as e:
            return ToolResult.error(f"Error searching files: {e}")
