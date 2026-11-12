# pyright: reportIncompatibleMethodOverride=false, reportPrivateUsage=false

from __future__ import annotations

import asyncio
import fnmatch
import heapq
import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from itertools import islice
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, TypeVar

from nanobot.agent.tools._search_content import ContentPage, MatchTooLargeError
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.filesystem import ListDirTool, _FsTool
from nanobot.execution.files import FileSearch, NotRegularFileError
from nanobot.utils.document import (
    DocumentLineSource,
    LocatedDocumentLine,
    PdfPageRangeError,
)

_DEFAULT_HEAD_LIMIT = 250
_DEFAULT_FILE_HEAD_LIMIT = 200
_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".pptx"})
_NON_TEXT_BYTES = re.compile(rb"[\x01-\x08\x0e-\x1f]")
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


@lru_cache(maxsize=128)
def _glob_path_parts(pattern: str) -> tuple[str, ...]:
    return PurePosixPath(pattern).parts


def _match_path_glob(rel_path: str, name: str, normalized: str) -> bool:
    if not normalized:
        return False
    if "/" in normalized:
        pattern_parts = _glob_path_parts(normalized)
        if len(pattern_parts) == 2 and pattern_parts[0] == "**" and pattern_parts[1] != "**":
            # Any directory prefix is allowed, so only the basename matters.
            return rel_path != "." and fnmatch.fnmatchcase(name, pattern_parts[1])
        path_parts = PurePosixPath(rel_path).parts
        matched = [True] + [False] * len(path_parts)
        for part in pattern_parts:
            if part == "**":
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
    return len(_NON_TEXT_BYTES.findall(sample)) / len(sample) > 0.2


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


def _ordered_prefix(
    items: Iterable[T], size: int | None, *, key: Callable[[T], tuple[float, str]],
) -> list[T]:
    return sorted(items, key=key) if size is None else heapq.nsmallest(size, items, key=key)


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


class _SearchTool(_FsTool):
    _IGNORE_DIRS = ListDirTool._IGNORE_DIRS | {".worktrees", ".worktree", ".nanobot"}
    _MAX_SCAN_PATHS = 500_000
    _MAX_SCAN_SECONDS = 30.0
    _MAX_RESULT_CHARS = 12_000

    @classmethod
    def _ignore_directory(cls, name: str) -> bool:
        return name in cls._IGNORE_DIRS or name.startswith(".verify-")

    def _display_path(self, target: Path, root: Path) -> str:
        workspace = self._files.display_workspace
        if workspace:
            with suppress(ValueError):
                return target.relative_to(workspace).as_posix()
        return target.relative_to(root).as_posix()

    def _iter_files(self, tree: FileSearch, budget: _SearchBudget) -> Iterable[Path]:
        if not tree.is_directory:
            budget.visit_path()
            yield tree.root
            return

        pending = [tree.root]
        while pending:
            budget.checkpoint()
            current = pending.pop()
            directories: list[str] = []
            filenames: list[str] = []
            try:
                for entry in tree.entries(current):
                    budget.checkpoint()
                    if not entry.is_directory:
                        filenames.append(entry.name)
                    else:
                        budget.visit_path()
                        if not entry.is_directory_link and not self._ignore_directory(entry.name):
                            directories.append(entry.name)
            except OSError:
                continue
            pending.extend(current / name for name in sorted(directories, reverse=True))
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

    def _directory_entries(
        self,
        tree: FileSearch,
        directory: Path,
        root: Path,
        budget: _SearchBudget,
    ) -> Iterator[_FindFilesEntry]:
        budget.checkpoint()
        try:
            for raw_entry in tree.entries(directory):
                budget.visit_path()
                is_dir = raw_entry.is_directory
                if raw_entry.is_directory_link or (is_dir and self._ignore_directory(raw_entry.name)):
                    continue
                yield self._entry(directory / raw_entry.name, root, is_dir=is_dir)
        except OSError:
            # os.walk silently skips directories that cannot be listed. Preserve
            # that behavior while still allowing cancellation and budget errors
            # to propagate from the explicit checkpoints above.
            pass

    def _push_directory_entries(
        self,
        tree: FileSearch,
        directory: Path,
        root: Path,
        frontier: list[tuple[str, int, _FindFilesEntry]],
        sequence: int,
        budget: _SearchBudget,
    ) -> int:
        for entry in self._directory_entries(tree, directory, root, budget):
            sort_path = entry.display_path + ("/" if entry.is_dir else "")
            heapq.heappush(frontier, (sort_path, sequence, entry))
            sequence += 1
        return sequence

    def _iter_paths(
        self,
        tree: FileSearch,
        *,
        include_dirs: bool,
        budget: _SearchBudget,
    ) -> Iterable[_FindFilesEntry]:
        budget.checkpoint()
        root = tree.root
        if not tree.is_directory:
            budget.visit_path()
            yield self._entry(root, root.parent, is_dir=False)
            return

        if include_dirs:
            yield self._entry(root, root, is_dir=True)

        frontier: list[tuple[str, int, _FindFilesEntry]] = []
        sequence = self._push_directory_entries(tree, root, root, frontier, 0, budget)
        while frontier:
            budget.checkpoint()
            _, _, entry = heapq.heappop(frontier)
            if entry.is_dir:
                if include_dirs:
                    yield entry
                sequence = self._push_directory_entries(
                    tree,
                    entry.path,
                    root,
                    frontier,
                    sequence,
                    budget,
                )
            else:
                yield entry

    def _iter_modified(
        self,
        tree: FileSearch,
        *,
        include_dirs: bool,
        matches: Callable[[_FindFilesEntry], bool],
        budget: _SearchBudget,
    ) -> Iterator[tuple[str, float]]:
        budget.checkpoint()
        root = tree.root
        if not tree.is_directory or include_dirs:
            if not tree.is_directory:
                budget.visit_path()
            entry = self._entry(root, root if tree.is_directory else root.parent, is_dir=tree.is_directory)
            if matches(entry):
                yield entry.display_path + ("/" if entry.is_dir else ""), tree.modified(root)
        if not tree.is_directory:
            return

        # Modified order needs a full scan; only the final selection needs a heap.
        pending = [root]
        while pending:
            directory = pending.pop()
            selected: list[_FindFilesEntry] = []
            for entry in self._directory_entries(tree, directory, root, budget):
                if entry.is_dir:
                    pending.append(entry.path)
                    if not include_dirs:
                        continue
                if matches(entry):
                    selected.append(entry)
            if selected:
                times = tree.modified_children(
                    directory, [entry.name for entry in selected], checkpoint=budget.checkpoint,
                )
                for entry, mtime in zip(selected, times, strict=True):
                    yield entry.display_path + ("/" if entry.is_dir else ""), mtime

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
                head_limit=int(head_limit) if head_limit is not None else None,
                offset=int(offset),
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
        try:
            tree = self._files.search_tree(path or ".")
        except FileNotFoundError:
            return ToolResult.error(f"Error: Path not found: {path}")
        except NotRegularFileError:
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

        terms = query.lower().split() if query else []

        def matches_entry(entry: _FindFilesEntry) -> bool:
            if glob and not _match_glob(entry.rel_path, entry.name, glob):
                return False
            if file_type and (entry.is_dir or not _matches_type(entry.name, file_type)):
                return False
            if not terms:
                return True
            haystack = entry.display_path.lower()
            return all(term in haystack for term in terms)

        selection_size = None if limit is None else offset + limit + 1
        try:
            if sort == "modified":
                by_modified = self._iter_modified(
                    tree, include_dirs=include_dirs, matches=matches_entry, budget=budget,
                )
                matches = _ordered_prefix(by_modified, selection_size, key=lambda item: (-item[1], item[0]))
                paths = [item[0] for item in matches]
            else:
                matching_paths = (
                    entry.display_path + ("/" if entry.is_dir else "")
                    for entry in self._iter_paths(tree, include_dirs=include_dirs, budget=budget)
                    if matches_entry(entry)
                )
                paths = list(islice(matching_paths, selection_size))
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
    def _text_source(raw: bytes, max_bytes: int) -> DocumentLineSource | None:
        if len(raw) > max_bytes or _is_binary(raw):
            return None
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return DocumentLineSource(
            LocatedDocumentLine(text, line_no, "")
            for line_no, text in enumerate(content.splitlines(), 1)
        )

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
                output_mode=output_mode, context_before=int(context_before), context_after=int(context_after),
                max_matches=int(max_matches) if max_matches is not None else None,
                max_results=int(max_results) if max_results is not None else None,
                head_limit=int(head_limit) if head_limit is not None else None,
                offset=int(offset), cancelled=cancelled,
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
            try:
                tree = self._files.search_tree(path or ".")
            except FileNotFoundError:
                return ToolResult.error(f"Error: Path not found: {path}")
            except NotRegularFileError:
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
            content_page = ContentPage(limit, offset, self._MAX_RESULT_CHARS, self._MAX_RENDERED_LINE_CHARS)
            skipped_binary = 0
            skipped_large = 0
            document_error: str | None = None
            document_continuations: list[str] = []
            counts: dict[str, int] = {}
            file_mtimes: dict[str, float] = {}
            root = tree.root if tree.is_directory else tree.root.parent
            max_file_bytes = (
                self._MAX_FILE_BYTES if tree.is_directory else self._MAX_EXPLICIT_FILE_BYTES
            )

            workspace = self._files.display_workspace
            with tree.search_bytes_reader() as read_bytes:
                for file_path in self._iter_files(tree, budget):
                    rel_path = file_path.relative_to(root).as_posix()
                    if glob and not _match_glob(rel_path, file_path.name, glob):
                        continue
                    if not _matches_type(file_path.name, type):
                        continue
                    display_path = rel_path
                    if workspace is not None and workspace != root:
                        with suppress(ValueError):
                            display_path = file_path.relative_to(workspace).as_posix()

                    source: DocumentLineSource | None = None
                    is_document = file_path.suffix.lower() in _DOCUMENT_EXTENSIONS
                    file_matches = 0
                    try:
                        if is_document:
                            try:
                                file = tree.read_file(file_path)
                            except OSError:
                                skipped_binary += 1
                                continue
                            if file.size > max_file_bytes:
                                skipped_large += 1
                                continue
                            mtime = file.modified
                            source = file.document_lines(pages=pages)
                        else:
                            contents = read_bytes(file_path, max_file_bytes)
                            if contents is None:
                                skipped_binary += 1
                                continue
                            if contents.data is None:
                                skipped_large += 1
                                continue
                            mtime = contents.modified
                            source = self._text_source(contents.data, max_file_bytes)
                        if source is None:
                            skipped_binary += 1
                            continue
                        if source.continuation and len(document_continuations) < 10:
                            document_continuations.append(
                                f"({display_path}: continue PDF search with {source.continuation})"
                            )
                        source_lines = checked_lines(source.lines)

                        if output_mode == "content":
                            content_page.scan(display_path, source_lines, regex, context_before, context_after)
                        else:
                            for line in source_lines:
                                if not line.searchable or regex.search(line.text) is None:
                                    continue
                                file_matches += 1
                                if output_mode != "count":
                                    break
                    except (_SearchCancelledError, _SearchBudgetExceededError, MatchTooLargeError):
                        raise
                    except Exception as e:
                        if not is_document:
                            raise
                        if not tree.is_directory:
                            if isinstance(e, PdfPageRangeError):
                                return ToolResult.error(
                                    f"Error: Invalid PDF page range '{pages}': {e!s}."
                                )
                            return ToolResult.error(
                                f"Error searching document {display_path}: {e!s}"
                            )
                        skipped_binary += 1
                        if document_error is None:
                            document_error = f"{display_path}: {e!s}"
                        continue
                    finally:
                        if source is not None:
                            source.close()
                        # A document can fail after yielding matches. Keep the count
                        # of those lines even though the failed file is not ranked.
                        if file_matches and output_mode == "count":
                            counts[display_path] = counts.get(display_path, 0) + file_matches
                    if file_matches:
                        file_mtimes[display_path] = mtime
                    if content_page.stopped:
                        break

            no_matches = f"No matches found for pattern '{pattern}' in {path}"
            notes: list[str] = []
            if output_mode == "content":
                result, note = content_page.render(no_matches)
                if note:
                    notes.append(note)
            else:
                ordered_files = _ordered_prefix(
                    file_mtimes, None if limit is None else offset + limit + 1,
                    key=lambda name: (-file_mtimes[name], name),
                )
                entries = (
                    [f"{name}: {counts[name]}" for name in ordered_files]
                    if output_mode == "count" else ordered_files
                )
                paged, truncated = _text_page(entries, limit, offset, self._MAX_RESULT_CHARS)
                result = "\n".join(paged) if file_mtimes or counts else no_matches
                if truncated:
                    notes.append(
                        f"(pagination: limit={limit}, offset={offset}; "
                        f"use offset={offset + len(paged)} to continue)"
                    )
                elif offset > 0:
                    notes.append(f"(pagination: offset={offset})")
            if skipped_binary:
                notes.append(f"(skipped {skipped_binary} binary/unreadable files)")
            if skipped_large:
                notes.append(f"(skipped {skipped_large} large files)")
            if document_error is not None:
                notes.append(f"(first document error: {document_error})")
            notes.extend(document_continuations)
            if output_mode == "count" and counts:
                notes.append(
                    f"(total matches: {sum(counts.values())} in {len(counts)} files)"
                )
            if notes:
                result += "\n\n" + "\n".join(notes)
            return result
        except MatchTooLargeError as exc:
            return ToolResult.error(f"Error: {exc}")
        except _SearchBudgetExceededError as exc:
            detail = f"{self._MAX_SCAN_PATHS} paths" if str(exc) == "paths" else f"{self._MAX_SCAN_SECONDS:g} seconds"
            return ToolResult.error(f"Error: grep scan exceeded {detail}; narrow path, glob, or type and retry.")
        except PermissionError as e:
            return ToolResult.error(f"Error: {e}")
        except Exception as e:
            return ToolResult.error(f"Error searching files: {e}")
