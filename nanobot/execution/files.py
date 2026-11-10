"""Filesystem operations and their workspace authorization."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable, Generator, Iterable
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from nanobot.config.paths import get_media_dir
from nanobot.security.workspace_access import current_tool_workspace
from nanobot.security.workspace_policy import resolve_allowed_path, resolve_path

if TYPE_CHECKING:
    from nanobot.utils.document import DocumentLineSource, PdfExtraction


class NotRegularFileError(OSError):
    """The opened resource is not a regular file."""


@contextmanager
def _open_regular_file(
    resolved_path: Path | str, *, dir_fd: int | None = None,
) -> Generator[tuple[BinaryIO, int]]:
    """Own one descriptor for the entire read and report its initial size.

    Callers must supply an authorized path or a child of an authorized directory handle.
    Where supported, refuse a swapped-in final symlink and avoid waiting on
    a swapped-in FIFO. This does not protect ancestor path components.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(resolved_path, flags, dir_fd=dir_fd), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise NotRegularFileError
        yield stream, opened.st_size


_BLOCKED_DEVICE_PATHS = frozenset({
    "/dev/zero", "/dev/random", "/dev/urandom", "/dev/full",
    "/dev/stdin", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/console",
    "/dev/fd/0", "/dev/fd/1", "/dev/fd/2",
})
_PROCESS_STDIO = re.compile(r"/proc/(?:[0-9]+|self)/fd/[012]$")


def _reject_device(path: str | Path, *, resolved: bool = False) -> None:
    raw = str(path)
    canonical = raw
    if not resolved:
        try:
            canonical = str(Path(raw).resolve())
        except (OSError, ValueError):
            pass
    if (
        raw in _BLOCKED_DEVICE_PATHS or canonical in _BLOCKED_DEVICE_PATHS
        or _PROCESS_STDIO.match(raw) or _PROCESS_STDIO.match(canonical)
        or canonical.startswith("/dev/")
    ):
        raise PermissionError(
            f"Reading {path} is blocked (device path that could hang or produce infinite output)."
        )


@dataclass(frozen=True, slots=True)
class ReadableFile:
    """A file selected by the workspace read policy."""

    path: Path
    size: int
    modified: float
    suffix: str

    def open(self) -> AbstractContextManager[tuple[BinaryIO, int]]:
        return _open_regular_file(self.path)

    @staticmethod
    def open_size(stream: BinaryIO) -> int:
        return os.fstat(stream.fileno()).st_size

    def pdf_pages(self, pages: str | None, *, max_pages: int, max_chars: int) -> PdfExtraction:
        from nanobot.utils.document import extract_pdf_pages

        return extract_pdf_pages(self.path, pages=pages, max_pages=max_pages, max_chars=max_chars)

    def document_lines(self, *, pages: str | None = None) -> DocumentLineSource | None:
        from nanobot.utils.document import open_document_line_source

        return open_document_line_source(self.path, pages=pages, suffix=self.suffix)


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    exists: bool
    text: str | None
    unreadable: bool = False
    binary: bool = False
    oversized: bool = False

    @property
    def countable(self) -> bool:
        return self.text is not None and not (self.binary or self.oversized or self.unreadable)


@dataclass(frozen=True, slots=True)
class WritableFile:
    """A selected write target; editing may inspect that file, not its parent."""

    path: Path

    def exists(self) -> bool:
        return self.path.exists()

    def is_file(self) -> bool:
        return self.path.is_file()

    def size(self) -> int:
        return self.path.stat().st_size

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()

    def write(self, content: str, *, create_parents: bool = False) -> None:
        if create_parents:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content, encoding="utf-8", newline="")

    def snapshot(self, max_bytes: int) -> FileSnapshot:
        """Read a bounded edit preview, not an independent path grant."""
        try:
            if not self.is_file():
                return FileSnapshot(exists=False, text="")
            with _open_regular_file(self.path) as (stream, size):
                if size > max_bytes:
                    return FileSnapshot(exists=True, text=None, oversized=True)
                raw = stream.read(max_bytes + 1)
        except OSError:
            return FileSnapshot(exists=self.exists(), text=None, unreadable=True)
        if len(raw) > max_bytes:
            return FileSnapshot(exists=True, text=None, oversized=True)
        if b"\x00" in raw:
            return FileSnapshot(exists=True, text=None, binary=True)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return FileSnapshot(exists=True, text=None, binary=True)
        return FileSnapshot(exists=True, text=text.replace("\r\n", "\n"))


def commit_file_edits(writes: dict[WritableFile, str]) -> None:
    """Write validated patch targets; restore their previous bytes on failure."""
    backups = {target: target.read_bytes() if target.exists() else None for target in writes}
    attempted: list[WritableFile] = []
    try:
        for target, content in writes.items():
            attempted.append(target)
            target.write(content, create_parents=True)
    except Exception:
        for target in attempted:
            data = backups[target]
            if data is None:
                target.path.unlink(missing_ok=True)
            else:
                target.path.parent.mkdir(parents=True, exist_ok=True)
                target.path.write_bytes(data)
        raise


@dataclass(frozen=True, slots=True)
class DirectoryListing:
    entries: list[tuple[Path, bool]]
    total: int


@dataclass(frozen=True, slots=True)
class SearchEntry:
    name: str
    is_directory: bool
    is_directory_link: bool


@dataclass(frozen=True, slots=True)
class SearchBytes:
    """A bounded read; no data means the regular file exceeds the size limit."""

    data: bytes | None
    modified: float


def _supports_directory_handles() -> bool:
    return (
        os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
    )


@dataclass(frozen=True, slots=True)
class FileSearch:
    """An authorized search root; links are not recursive directories."""

    root: Path
    is_directory: bool
    _authorize_read: Callable[[str | Path], Path]

    def entries(self, directory: Path) -> Generator[SearchEntry]:
        target = resolve_path(directory)
        if not self.is_directory or not target.is_relative_to(self.root) or target != directory:
            return
        with os.scandir(target) as entries:
            for entry in entries:
                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                    directory_link = not is_directory and entry.is_symlink() and entry.is_dir()
                    if os.name == "nt" and is_directory:
                        directory_link = bool(
                            entry.stat(follow_symlinks=False).st_file_attributes
                            & stat.FILE_ATTRIBUTE_REPARSE_POINT
                        )
                except OSError:
                    continue
                yield SearchEntry(entry.name, is_directory or directory_link, directory_link)

    def _candidate(self, path: Path) -> Path:
        target = Path(os.path.realpath(path, strict=True))
        if target == self.root or (self.is_directory and target.is_relative_to(self.root)):
            return target
        return self._authorize_read(path)

    def modified(self, path: Path) -> float:
        try:
            return self._candidate(path).stat().st_mtime
        except OSError:
            return 0.0

    @contextmanager
    def _open_search_directory(self, directory: Path) -> Generator[int]:
        """Pin a directory for a scan and validate it before releasing results."""
        relative = directory.relative_to(self.root)
        if ".." in relative.parts:
            raise ValueError("Expected a directory within the search root")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        root_info = self.root.stat(follow_symlinks=False)
        fd = os.open(self.root, flags)
        try:
            if not os.path.samestat(root_info, os.fstat(fd)):
                raise PermissionError("Search root changed")
            for part in relative.parts:
                child = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
            # A descriptor survives a rename. Discard its results if the
            # authorized path no longer points to the directory we scanned.
            try:
                if (
                    Path(os.path.realpath(directory, strict=True)) == directory
                    and os.path.samestat(os.fstat(fd), directory.stat(follow_symlinks=False))
                ):
                    return
            except OSError:
                pass
            raise PermissionError("Search directory changed during the scan; retry the search.")
        finally:
            os.close(fd)

    def modified_children(
        self, directory: Path, names: list[str], *, checkpoint: Callable[[], None],
    ) -> list[float]:
        """Get timestamps for direct children without transferring the directory handle."""
        if not self.is_directory or not directory.is_relative_to(self.root) or ".." in directory.parts:
            raise ValueError("Expected a directory within the search root")
        if any(not name or name in (".", "..") or os.path.basename(name) != name for name in names):
            raise ValueError("Expected direct child names")

        # A small match set does not amortize opening and rechecking the directory.
        if len(names) >= 4 and _supports_directory_handles():
            try:
                with self._open_search_directory(directory) as fd:
                    times: list[float] = []
                    for name in names:
                        checkpoint()
                        try:
                            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        except OSError:
                            times.append(0.0)
                        else:
                            times.append(
                                self.modified(directory / name) if stat.S_ISLNK(info.st_mode)
                                else info.st_mtime
                            )
                    return times
            except OSError:
                pass  # Reauthorize each child if the directory could not be pinned.

        times = []
        for name in names:
            checkpoint()
            times.append(self.modified(directory / name))
        return times

    def read_file(self, path: Path) -> ReadableFile:
        return _regular_file(self._candidate(path), suffix=path.suffix.lower())

    def _read_search_bytes(self, path: Path, limit: int, fd: int | None = None) -> SearchBytes | None:
        if fd is None:
            try:
                file = self.read_file(path)
            except OSError:
                return None
            size, modified = file.size, file.modified
            opened_path = file.path
        else:
            try:
                info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            except OSError:
                return None
            if stat.S_ISLNK(info.st_mode):
                return self._read_search_bytes(path, limit)
            if not stat.S_ISREG(info.st_mode):
                return None
            size, modified = info.st_size, info.st_mtime
            opened_path = path.name
        if size > limit:
            return SearchBytes(None, modified)
        with _open_regular_file(opened_path, dir_fd=fd) as (stream, opened_size):
            if opened_size > limit:
                return None
            return SearchBytes(stream.read(limit + 1), modified)

    @contextmanager
    def search_bytes_reader(self) -> Generator[Callable[[Path, int], SearchBytes | None]]:
        """Read consecutive files using one pinned parent; no handle leaves execution."""
        if not self.is_directory or not _supports_directory_handles():
            yield self._read_search_bytes
            return

        parent: Path | None = None
        fd: int | None = None
        attempted = False
        with ExitStack() as handle:
            def read(path: Path, limit: int) -> SearchBytes | None:
                nonlocal parent, fd, attempted
                directory = path.parent
                if directory != parent:
                    handle.close()
                    parent, fd, attempted = directory, None, False
                    return self._read_search_bytes(path, limit)
                if not attempted:
                    attempted = True
                    # Only open directories with multiple candidates. If the host
                    # cannot pin this path, keep using per-file authorization.
                    try:
                        _reject_device(directory, resolved=True)
                        fd = handle.enter_context(self._open_search_directory(directory))
                    except (OSError, ValueError):
                        pass
                if path.name in ("", ".", ".."):
                    return self._read_search_bytes(path, limit)
                return self._read_search_bytes(path, limit, fd)

            yield read


def _regular_file(target: Path, *, suffix: str | None = None) -> ReadableFile:
    _reject_device(target, resolved=True)
    info = target.stat()
    if not stat.S_ISREG(info.st_mode):
        raise NotRegularFileError
    return ReadableFile(target, info.st_size, info.st_mtime, target.suffix.lower() if suffix is None else suffix)


class WorkspaceFiles:
    """File operations authorized against the effective request's workspace."""

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        extra_allowed_dirs: Iterable[Path] | None = None,
        extra_read_allowed_dirs: Iterable[Path] | None = None,
        extra_write_allowed_dirs: Iterable[Path] | None = None,
        extra_write_allowed_files: Iterable[Path] | None = None,
        restrict_to_workspace: bool | None = None,
        sandbox_restricts_workspace: bool = False,
        extra_read_allowed_files: Iterable[Path] | None = None,
        *,
        builtin_skills: Path,
        plugin_skill_roots: Callable[[Path, Path], Iterable[Path]],
    ) -> None:
        self._workspace = workspace
        self._allowed_dir = allowed_dir
        # The legacy extra_allowed_dirs option only grants reads.
        self._read_dirs = (*tuple(extra_allowed_dirs or ()), *tuple(extra_read_allowed_dirs or ()))
        self._read_files = tuple(extra_read_allowed_files or ())
        self._write_dirs = tuple(extra_write_allowed_dirs or ())
        self._write_files = tuple(extra_write_allowed_files or ())
        self._restricted = (
            restrict_to_workspace if restrict_to_workspace is not None else allowed_dir is not None
        )
        self._sandbox_restricted = sandbox_restricts_workspace
        self._builtin_skills = builtin_skills
        self._plugin_skill_roots = plugin_skill_roots

    @classmethod
    def for_agent(
        cls,
        workspace: Path,
        *,
        restrict_to_workspace: bool,
        sandbox_restricts_workspace: bool,
        builtin_skills: Path,
        plugin_skill_roots: Callable[[Path, Path], Iterable[Path]],
    ) -> WorkspaceFiles:
        root = workspace.expanduser().resolve(strict=False)
        return cls(
            workspace,
            allowed_dir=workspace if restrict_to_workspace or sandbox_restricts_workspace else None,
            extra_read_allowed_dirs=[builtin_skills, root / "skills"],
            extra_read_allowed_files=[root / "memory" / "history.jsonl"],
            restrict_to_workspace=restrict_to_workspace,
            sandbox_restricts_workspace=sandbox_restricts_workspace,
            builtin_skills=builtin_skills,
            plugin_skill_roots=plugin_skill_roots,
        )

    @property
    def display_workspace(self) -> Path | None:
        return current_tool_workspace(self._workspace).project_path

    def _allowed_root(self, request_root: Path | None) -> Path | None:
        if self._allowed_dir is None or self._workspace is None:
            return request_root
        try:
            if Path(self._allowed_dir).expanduser().resolve() == Path(self._workspace).expanduser().resolve():
                return request_root
        except (OSError, RuntimeError, TypeError, ValueError):
            return request_root if request_root is not None else self._allowed_dir
        return self._allowed_dir

    def _roots(self) -> tuple[Path | None, Path | None]:
        access = current_tool_workspace(
            self._workspace,
            restrict_to_workspace=self._restricted,
            sandbox_restricts_workspace=self._sandbox_restricted,
        )
        return access.project_path, self._allowed_root(access.allowed_root)

    def _read_path(self, path: str | Path) -> Path:
        workspace, root = self._roots()
        extra_roots: list[Path] = []
        if root is not None:
            extra_roots = [get_media_dir(), *self._read_dirs]
            if self._workspace is not None:
                try:
                    extra_roots.extend(self._plugin_skill_roots(self._workspace, resolve_path(path, workspace)))
                except (OSError, RuntimeError):
                    pass
        return resolve_allowed_path(
            path,
            workspace=workspace,
            allowed_root=root,
            extra_allowed_roots=extra_roots,
            extra_allowed_files=self._read_files if root is not None else (),
        )

    def edit_target(self, path: str) -> WritableFile:
        workspace, root = self._roots()
        return WritableFile(resolve_allowed_path(
            path,
            workspace=workspace,
            allowed_root=root,
            extra_allowed_roots=self._write_dirs if root is not None else (),
            extra_allowed_files=self._write_files,
        ))

    def read_file(self, path: str) -> ReadableFile:
        _reject_device(path)
        target = self._read_path(path)
        if not target.exists():
            requested = Path(path)
            parts = requested.parts
            if not requested.is_absolute() and len(parts) >= 2 and parts[0] == "skills":
                builtin = self._builtin_skills.resolve()
                candidate = (builtin / Path(*parts[1:])).resolve()
                if candidate.is_relative_to(builtin) and candidate.is_file():
                    target = candidate
        if not target.exists():
            _reject_device(target, resolved=True)
            raise FileNotFoundError(path)
        return _regular_file(target)

    def list_directory(
        self, path: str, *, recursive: bool, ignored: set[str], limit: int,
    ) -> DirectoryListing:
        directory = self._read_path(path)
        if not directory.exists():
            raise FileNotFoundError(path)
        if not directory.is_dir():
            raise NotADirectoryError(path)
        tree = FileSearch(directory, True, self._read_path)
        pending = [directory]
        entries: list[tuple[Path, bool]] = []
        while pending:
            parent = pending.pop()
            try:
                for entry in tree.entries(parent):
                    if entry.name in ignored:
                        continue
                    child = parent / entry.name
                    entries.append((child.relative_to(directory), entry.is_directory))
                    if recursive and entry.is_directory and not entry.is_directory_link:
                        pending.append(child)
            except PermissionError:
                if not recursive:
                    raise
        entries.sort(key=lambda entry: entry[0])
        return DirectoryListing(entries[:max(0, limit)], len(entries))

    def sibling_files(self, target: WritableFile) -> list[str]:
        """Suggest names only when the caller can read the directory itself."""
        try:
            parent = self._read_path(target.path.parent)
        except PermissionError:
            return []
        return [item.name for item in parent.iterdir() if item.is_file()] if parent.is_dir() else []

    def search_tree(self, path: str) -> FileSearch:
        target = self._read_path(path)
        mode = target.stat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise NotRegularFileError
        return FileSearch(target, stat.S_ISDIR(mode), self._read_path)
