from __future__ import annotations

import io
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from loguru import logger

from nanobot.config.paths import DREAM_CURSOR_PATH

if TYPE_CHECKING:
    from dulwich.objects import Blob, Commit, ObjectID, Tree
    from dulwich.refs import Ref
    from dulwich.repo import Repo

# Cap on the unified-diff block embedded in Dream commit messages. Memory files
# are tiny in practice, but a pathological rewrite must not blow up the audit
# record. The structured per-file summary is always emitted in full regardless.
_WORKING_TREE_DIFF_MAX_CHARS = 6000
MEMORY_CONTENT_PATHS = ("SOUL.md", "USER.md", "memory/MEMORY.md")
MEMORY_WIKI_PATH = "memory/wiki"


class GitStoreError(RuntimeError):
    """Raised when the memory Git repository cannot complete an operation."""


class GitStoreDirtyError(GitStoreError):
    """Restore was refused before changing any files or Git state."""


@dataclass
class CommitInfo:
    sha: str  # Short SHA (8 chars)
    message: str
    timestamp: str

    def subject(self) -> str:
        """First line of the commit message, or a placeholder if empty."""
        lines = self.message.splitlines()
        return lines[0] if lines else "(no message)"

    def format(self, diff: str = "") -> str:
        """Format this commit for display, optionally with a diff."""
        header = f"## {self.subject()}\n`{self.sha}` — {self.timestamp}\n"
        if diff:
            return f"{header}\n```diff\n{diff}\n```"
        return f"{header}\n(no file changes)"


class GitStore:
    """Git-backed memory files and optional recursive, link-free directories."""

    def __init__(
        self,
        workspace: Path,
        tracked_files: list[str],
        *,
        tracked_dirs: list[str] | None = None,
        tracked_state_files: tuple[str, ...] = (),
    ):
        self._workspace = workspace
        self._content_files = tracked_files
        self._state_files = tracked_state_files
        self._tracked_files = [*tracked_files, *tracked_state_files]
        self._tracked_dirs = [Path(path).as_posix() for path in tracked_dirs or []]

    @classmethod
    def for_memory(cls, workspace: Path) -> GitStore:
        return cls(
            workspace,
            tracked_files=list(MEMORY_CONTENT_PATHS),
            tracked_dirs=[MEMORY_WIKI_PATH],
            tracked_state_files=(DREAM_CURSOR_PATH.as_posix(),),
        )

    def is_initialized(self) -> bool:
        """Check if the git repo has been initialized."""
        return (self._workspace / ".git").is_dir()


    def init(self) -> bool:
        """Initialize a git repo if not already initialized.

        Creates .gitignore and makes an initial commit.
        Returns True if a new repo was created, False if already exists.
        """
        if self.is_initialized():
            return False

        if self._is_inside_git_repo():
            logger.warning(
                "Workspace {} is already inside a git repo; "
                "skipping nested repo initialization",
                self._workspace,
            )
            return False

        try:
            from dulwich import porcelain

            # Validate directory grants before creating any files through their ancestors.
            self._directory_files(self._tracked_dirs)
            porcelain.init(str(self._workspace))

            gitignore = self._workspace / ".gitignore"
            dream_entries = self._build_gitignore()
            if gitignore.exists():
                existing = gitignore.read_text(encoding="utf-8")
                existing_lines = set(existing.splitlines())
                new_lines = [
                    line
                    for line in dream_entries.splitlines()
                    if line not in existing_lines
                ]
                if new_lines:
                    merged = existing.rstrip("\n") + "\n" + "\n".join(new_lines) + "\n"
                    gitignore.write_text(merged, encoding="utf-8")
            else:
                gitignore.write_text(dream_entries, encoding="utf-8")

            for rel in self._tracked_files:
                p = self._workspace / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_text("", encoding="utf-8")

            self._stage(".gitignore")
            porcelain.commit(
                str(self._workspace),
                message=b"init: nanobot memory store",
                author=b"nanobot <nanobot@dream>",
                committer=b"nanobot <nanobot@dream>",
            )
            logger.debug("Git store initialized at {}", self._workspace)
            return True
        except Exception as exc:
            raise GitStoreError(f"Git store init failed for {self._workspace}") from exc


    def auto_commit(self, message: str) -> str | None:
        """Stage tracked memory files and commit if there are changes.

        Returns the short commit SHA, or None if nothing to commit.
        """
        if not self.is_initialized():
            return None

        try:
            from dulwich import porcelain

            # Stage first so Dulwich refreshes the content hashes.  A status
            # check can miss rapid same-size rewrites when the filesystem also
            # preserves the file's mtime.
            self._stage()
            st = porcelain.status(str(self._workspace))
            staged = cast(dict[object, list[object]], st.staged)
            if not any(staged.values()):
                return None

            message_value = cast(object, message)
            msg_bytes = (
                message_value.encode("utf-8")
                if isinstance(message_value, str)
                else cast(bytes, message_value)
            )
            sha_bytes = porcelain.commit(
                str(self._workspace),
                message=msg_bytes,
                author=b"nanobot <nanobot@dream>",
                committer=b"nanobot <nanobot@dream>",
            )
            if cast(object, sha_bytes) is None:
                return None
            # porcelain.commit returns the id as a 40-char hex string that is
            # already encoded to bytes; .hex() would encode those ASCII bytes
            # again and produce an id no git command can resolve.
            sha = sha_bytes.decode()[:8]
            logger.debug("Git auto-commit: {} ({})", sha, message)
            return sha
        except Exception as exc:
            raise GitStoreError(f"Git auto-commit failed: {message}") from exc


    def _staging_paths(self, *paths: str) -> list[str]:
        return [str((self._workspace / path).absolute()) for path in paths]

    def _directory_path(self, relative: str) -> Path:
        """Reject links (including Windows junctions) anywhere in a directory grant.

        Like the workspace file guards, this is not confinement against concurrent
        replacement of ancestor directories by another process.
        """
        path = Path(relative)
        if path.anchor or not path.parts or any(
            part == ".." or part.lower() == ".git" for part in path.parts
        ):
            raise GitStoreError(f"Invalid managed directory path: {relative}")
        dest = self._workspace
        for part in path.parts:
            dest = dest / part
            try:
                info = dest.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise GitStoreError(f"Links are not allowed in managed directories: {relative}")
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise GitStoreError(f"Unsupported managed directory entry: {relative}")
        return dest

    def _directory_files(self, directories: list[str]) -> set[str]:
        """Enumerate only regular files, checking before descending or opening."""
        files: set[str] = set()
        for directory in directories:
            root = self._directory_path(directory)
            if not root.exists():
                continue
            if not root.is_dir():
                raise GitStoreError(f"Managed directory is not a directory: {directory}")
            pending = [root]
            while pending:
                for path in pending.pop().iterdir():
                    relative = path.relative_to(self._workspace).as_posix()
                    self._directory_path(relative)
                    if path.is_dir():
                        pending.append(path)
                    else:
                        files.add(relative)
        return files

    @staticmethod
    def _in_directories(path: str, directories: list[str]) -> bool:
        return any(path == directory or path.startswith(directory + "/") for directory in directories)

    def _directory_tree_files(
        self, repo: "Repo", tree: "Tree | None", directories: list[str],
    ) -> dict[str, "ObjectID"]:
        from dulwich.object_store import iter_tree_contents

        files: dict[str, ObjectID] = {}
        if tree is not None and directories:
            for entry in iter_tree_contents(repo.object_store, tree.id):
                relative = entry.path.decode("utf-8")
                if self._in_directories(relative, directories):
                    if not stat.S_ISREG(entry.mode):
                        raise GitStoreError(f"Unsupported managed directory snapshot: {relative}")
                    files[relative] = entry.sha
        return files

    def _stage(self, *extra_files: str) -> None:
        from dulwich import porcelain
        from dulwich.repo import Repo

        with Repo(str(self._workspace)) as repo:
            paths = self._directory_files(self._tracked_dirs)
            paths.update(self._directory_tree_files(repo, self._head_tree(repo), self._tracked_dirs))
            paths.update(
                path.decode("utf-8") for path in repo.open_index()
                if self._in_directories(path.decode("utf-8"), self._tracked_dirs)
            )
            for path in paths:
                self._directory_path(path)
            porcelain.add(
                str(self._workspace),
                paths=self._staging_paths(*extra_files, *self._content_files),
            )
            # Older workspaces may ignore newly managed wiki and cursor files.
            repo.get_worktree().stage(sorted(paths.union(self._state_files)))

    def _resolve_sha(self, short_sha: str) -> bytes | None:
        try:
            from dulwich.repo import Repo

            with Repo(str(self._workspace)) as repo:
                try:
                    sha: ObjectID | None = repo.refs[cast("Ref", b"HEAD")]
                except KeyError:
                    return None

                while sha:
                    if sha.decode().startswith(short_sha):
                        return sha
                    commit_obj = repo[sha]
                    if commit_obj.type_name != b"commit":
                        break
                    commit = cast("Commit", commit_obj)
                    sha = commit.parents[0] if commit.parents else None
            return None
        except Exception as exc:
            raise GitStoreError(f"Git SHA resolution failed: {short_sha}") from exc

    def _is_inside_git_repo(self) -> bool:
        """Check if self._workspace is already inside a git repository.

        Walks up from self._workspace to the filesystem root, returning True
        if any parent directory contains a .git entry.

        Git worktrees and submodules can use a ``.git`` file instead of a
        directory, so we must treat either form as "already inside a repo".
        """
        current = self._workspace.resolve()
        while current != current.parent:
            if (current / ".git").exists():
                return True
            current = current.parent
        return False

    def _build_gitignore(self) -> str:
        dirs: set[str] = set()
        for path in [*self._tracked_files, *self._tracked_dirs]:
            dirs.update(parent.as_posix() for parent in Path(path).parents if parent != Path("."))
        lines = ["/*"]
        for d in sorted(dirs):
            lines.extend([f"!{d}/", f"{d}/*"])
        for f in self._tracked_files:
            lines.append(f"!{f}")
        for d in self._tracked_dirs:
            lines.extend([f"!{d}/", f"!{d}/**"])
        lines.append("!.gitignore")
        return "\n".join(lines) + "\n"


    def log(
        self,
        max_entries: int = 20,
        message_prefix: str | None = None,
    ) -> list[CommitInfo]:
        """Return simplified commit log, optionally filtered by message prefix.

        When filtering, *max_entries* counts matching commits rather than every
        commit traversed in the repository.
        """
        if not self.is_initialized():
            return []

        try:
            from dulwich.repo import Repo

            entries: list[CommitInfo] = []
            with Repo(str(self._workspace)) as repo:
                try:
                    head = repo.refs[cast("Ref", b"HEAD")]
                except KeyError:
                    return []

                sha: ObjectID | None = head
                while sha and len(entries) < max_entries:
                    commit_obj = repo[sha]
                    if commit_obj.type_name != b"commit":
                        break
                    commit = cast("Commit", commit_obj)
                    ts = time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.localtime(commit.commit_time),
                    )
                    msg = commit.message.decode("utf-8", errors="replace").strip()
                    if message_prefix is None or msg.startswith(message_prefix):
                        entries.append(CommitInfo(
                            sha=sha.decode()[:8],
                            message=msg,
                            timestamp=ts,
                        ))
                    sha = commit.parents[0] if commit.parents else None

            return entries
        except Exception as exc:
            raise GitStoreError("Git log failed") from exc

    def diff_commits(self, sha1: str, sha2: str) -> str:
        """Show diff between two commits."""
        if not self.is_initialized():
            return ""

        try:
            from dulwich import porcelain

            full1 = self._resolve_sha(sha1)
            full2 = self._resolve_sha(sha2)
            if not full1 or not full2:
                return ""

            out = io.BytesIO()
            porcelain.diff(
                str(self._workspace),
                commit=full1,
                commit2=full2,
                outstream=out,
            )
            return out.getvalue().decode("utf-8", errors="replace")
        except Exception as exc:
            raise GitStoreError(f"Git diff failed for {sha1}..{sha2}") from exc

    def summarize_working_tree(
        self, paths: list[str], *, directories: list[str] | None = None,
    ) -> str:
        """Structured summary of working-tree changes vs HEAD for selected paths.

        *directories* recursively includes both current and deleted files; it does
        not implicitly include every tracked file (such as the Dream cursor).
        Pure filesystem/git ground truth — never LLM narrative — suitable as a
        truthful audit record. Returns "" when the repo is not initialized or
        none of the selected files differ from HEAD.

        Format::

            SOUL.md: +3 -1
            memory/MEMORY.md: +12 -8

            2 files changed, 15 insertions(+), 9 deletions(-)

            ```diff
            --- SOUL.md
            +++ SOUL.md
            @@ ...
            - old
            + new
            ```
        """
        if not self.is_initialized():
            return ""

        try:
            import difflib

            from dulwich.repo import Repo
        except ImportError as exc:
            raise GitStoreError("Git working-tree summary dependencies are unavailable") from exc

        summary_lines: list[str] = []
        diff_lines: list[str] = []
        total_added = 0
        total_removed = 0
        changed = 0

        try:
            with Repo(str(self._workspace)) as repo:
                head_tree = self._head_tree(repo)
                directories = [Path(path).as_posix() for path in directories or []]
                directory_paths = self._directory_files(directories)
                directory_paths.update(self._directory_tree_files(repo, head_tree, directories))
                for path in directory_paths:
                    self._directory_path(path)
                for path in dict.fromkeys([*paths, *sorted(directory_paths)]):
                    if self._in_directories(Path(path).as_posix(), self._tracked_dirs):
                        self._directory_path(path)
                    head_text = (
                        self._read_blob_from_tree(repo, head_tree, path)
                        if head_tree is not None
                        else None
                    )
                    head_exists = head_text is not None
                    if head_text is None:
                        head_text = ""
                    wt_path = self._workspace / path
                    wt_exists = wt_path.exists()
                    try:
                        wt_text = wt_path.read_bytes().decode("utf-8") if wt_exists else ""
                    except UnicodeDecodeError:
                        # Non-UTF-8 (binary/corrupt) working-tree file: record
                        # the change without a unified diff, which would
                        # otherwise be polluted with replacement characters and
                        # misrepresent the audit record.
                        changed += 1
                        summary_lines.append(f"{path}: binary or non-UTF-8 file changed")
                        continue
                    # Treat CRLF and LF as equivalent without hiding other
                    # newline changes, such as a missing final newline.
                    if head_exists == wt_exists and head_text.replace("\r\n", "\n") == wt_text.replace("\r\n", "\n"):
                        continue
                    head_lines = head_text.splitlines()
                    wt_lines = wt_text.splitlines()
                    changed += 1
                    hunks = list(difflib.unified_diff(
                        head_lines,
                        wt_lines,
                        fromfile=path,
                        tofile=path,
                        lineterm="",
                    ))
                    added = sum(1 for line in hunks if line.startswith("+") and not line.startswith("+++"))
                    removed = sum(1 for line in hunks if line.startswith("-") and not line.startswith("---"))
                    total_added += added
                    total_removed += removed
                    summary_lines.append(f"{path}: +{added} -{removed}")
                    diff_lines.extend(hunks)
        except Exception as exc:
            raise GitStoreError("Git working-tree summary failed") from exc

        if changed == 0:
            return ""

        diff_text = "\n".join(diff_lines)
        if len(diff_text) > _WORKING_TREE_DIFF_MAX_CHARS:
            diff_text = diff_text[:_WORKING_TREE_DIFF_MAX_CHARS] + "\n...[diff truncated]"

        body = "\n".join(summary_lines)
        body += (
            f"\n{changed} file{'s' if changed != 1 else ''} changed, "
            f"{total_added} insertion{'s' if total_added != 1 else ''}(+), "
            f"{total_removed} deletion{'s' if total_removed != 1 else ''}(-)"
        )
        if diff_lines:
            body += f"\n\n```diff\n{diff_text}\n```"
        return body

    @staticmethod
    def _head_tree(repo: "Repo") -> "Tree | None":
        """Return the tree object at HEAD, or None if there are no commits."""
        try:
            head = repo.refs[cast("Ref", b"HEAD")]
        except KeyError:
            return None
        commit_obj = repo[head]
        if commit_obj.type_name != b"commit":
            return None
        commit = cast("Commit", commit_obj)
        return cast("Tree", repo[commit.tree])

    def show_commit_diff(
        self,
        short_sha: str,
        max_entries: int = 20,
        message_prefix: str | None = None,
    ) -> tuple[CommitInfo, str] | None:
        """Find a commit and return it with its diff vs its actual parent."""
        try:
            from dulwich.repo import Repo

            commits = self.log(max_entries=max_entries, message_prefix=message_prefix)
            for c in commits:
                if c.sha.startswith(short_sha):
                    full_sha = self._resolve_sha(c.sha)
                    if not full_sha:
                        return None
                    with Repo(str(self._workspace)) as repo:
                        commit = cast("Commit", repo[full_sha])
                        parent = commit.parents[0] if commit.parents else None
                    diff = self.diff_commits(parent.decode()[:8], c.sha) if parent else ""
                    return c, diff
            return None
        except Exception as exc:
            raise GitStoreError(f"Git commit display failed for {short_sha}") from exc


    def _require_clean_restore(self, repo: "Repo", current_pages: set[str]) -> None:
        from dulwich import porcelain
        from dulwich.objects import Blob

        # A restore commit uses the whole index. Do not consume pre-staged changes.
        if any(porcelain.get_tree_changes(repo).values()):
            raise GitStoreDirtyError("The memory repository has staged changes.")

        head = self._head_tree(repo)
        head_pages = self._directory_tree_files(repo, head, self._tracked_dirs)
        normalizer = repo.get_blob_normalizer()
        for path in sorted({*self._content_files, *current_pages, *head_pages}):
            git_path = path.encode("utf-8")
            try:
                mode, sha = head.lookup_path(repo.__getitem__, git_path) if head else (0, None)
            except KeyError:
                mode, sha = 0, None
            dest = self._workspace / path
            try:
                worktree_mode = dest.lstat().st_mode
            except FileNotFoundError:
                if sha is None:
                    continue
            else:
                if sha is not None and stat.S_ISREG(mode) and stat.S_ISREG(worktree_mode):
                    blob = normalizer.checkin_normalize(Blob.from_string(dest.read_bytes()), git_path)
                    if blob.id == sha:
                        continue
            raise GitStoreDirtyError(f"Memory has uncommitted changes in `{path}`.")

    def revert(self, commit: str, *, message_prefix: str | None = None) -> str | None:
        """Revert (undo) the changes introduced by the given commit.

        Restores tracked files and directory contents to the commit's parent,
        removing directory files absent there, then commits the restore. When *message_prefix*
        is provided, commits outside that history are rejected before any files
        are changed.

        Refuses staged changes or uncommitted content changes before restoring.
        Unstaged runtime state may differ from HEAD between versions.
        Returns the new commit SHA, or ``None`` when the commit cannot be reverted.
        Repository and filesystem failures raise :class:`GitStoreError`.
        """
        if not self.is_initialized():
            return None

        try:
            from dulwich.repo import Repo

            full_sha = self._resolve_sha(commit)
            if not full_sha:
                logger.warning("Git revert: SHA not found: {}", commit)
                return None

            with Repo(str(self._workspace)) as repo:
                commit_obj = repo[full_sha]
                if commit_obj.type_name != b"commit":
                    return None
                typed_commit = cast("Commit", commit_obj)

                commit_message = typed_commit.message.decode(
                    "utf-8",
                    errors="replace",
                ).strip()
                if message_prefix is not None and not commit_message.startswith(message_prefix):
                    logger.warning(
                        "Git revert: commit {} does not match message prefix {!r}",
                        commit,
                        message_prefix,
                    )
                    return None

                if not typed_commit.parents:
                    logger.warning("Git revert: cannot revert root commit {}", commit)
                    return None

                parent_obj = cast("Commit", repo[typed_commit.parents[0]])
                tree = cast("Tree", repo[parent_obj.tree])

                current_pages = self._directory_files(self._tracked_dirs)
                self._require_clean_restore(repo, current_pages)
                target_pages = self._directory_tree_files(repo, tree, self._tracked_dirs)
                # Validate the complete restore before changing even the fixed files.
                for filepath in target_pages:
                    self._directory_path(filepath)

                restored: list[str] = []
                for filepath in self._tracked_files:
                    content = self._read_blob_from_tree(repo, tree, filepath)
                    if content is not None:
                        dest = self._workspace / filepath
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(content, encoding="utf-8")
                        restored.append(filepath)
                for filepath in current_pages - target_pages.keys():
                    self._directory_path(filepath).unlink()
                for filepath, blob_id in target_pages.items():
                    dest = self._directory_path(filepath)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(cast("Blob", repo[blob_id]).data)

            if not restored and not self._tracked_dirs:
                return None

            msg = f"revert: undo {commit}"
            return self.auto_commit(msg)
        except GitStoreDirtyError:
            raise
        except Exception as exc:
            raise GitStoreError(f"Git revert failed for {commit}") from exc

    @staticmethod
    def _read_blob_from_tree(
        repo: "Repo",
        tree: "Tree",
        filepath: str,
    ) -> str | None:
        """Read a blob's content from a tree object by walking path parts."""
        parts = Path(filepath).parts
        current = tree
        for part in parts:
            try:
                entry = current[part.encode()]
            except KeyError:
                return None
            obj = repo[entry[1]]
            if obj.type_name == b"blob":
                blob = cast("Blob", obj)
                return blob.data.decode("utf-8", errors="replace")
            if obj.type_name == b"tree":
                current = cast("Tree", obj)
            else:
                return None
        return None
