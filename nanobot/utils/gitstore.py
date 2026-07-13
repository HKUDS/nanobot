"""Git-backed version control for memory files, using dulwich."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# Cap on the unified-diff block embedded in Dream commit messages. Memory files
# are tiny in practice, but a pathological rewrite must not blow up the audit
# record. The structured per-file summary is always emitted in full regardless.
_WORKING_TREE_DIFF_MAX_CHARS = 6000


@dataclass
class CommitInfo:
    sha: str  # Short SHA (8 chars)
    message: str
    timestamp: str  # Formatted datetime

    def format(self, diff: str = "") -> str:
        """Format this commit for display, optionally with a diff."""
        header = f"## {self.message.splitlines()[0]}\n`{self.sha}` — {self.timestamp}\n"
        if diff:
            return f"{header}\n```diff\n{diff}\n```"
        return f"{header}\n(no file changes)"


@dataclass
class LineAge:
    """Age of a single line based on git blame."""

    age_days: int  # days since last modification


def _compute_line_ages(annotated) -> list[LineAge]:
    """Convert annotate results to per-line ages."""
    now = datetime.now(tz=timezone.utc).date()
    ages: list[LineAge] = []
    for (commit, _tree_entry), _line_bytes in annotated:
        dt = datetime.fromtimestamp(commit.commit_time, tz=timezone.utc).date()
        ages.append(LineAge(age_days=(now - dt).days))
    return ages


class GitStore:
    """Git-backed version control for memory files."""

    def __init__(self, workspace: Path, tracked_files: list[str]):
        self._workspace = workspace
        self._tracked_files = tracked_files

    def is_initialized(self) -> bool:
        """Check if the git repo has been initialized."""
        return (self._workspace / ".git").is_dir()

    # -- init ------------------------------------------------------------------

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

            porcelain.init(str(self._workspace))

            # Write .gitignore (merge with existing if present)
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

            # Ensure tracked files exist (touch them if missing) so the initial
            # commit has something to track.
            for rel in self._tracked_files:
                p = self._workspace / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_text("", encoding="utf-8")

            # Initial commit
            porcelain.add(str(self._workspace), paths=[".gitignore"] + self._tracked_files)
            porcelain.commit(
                str(self._workspace),
                message=b"init: nanobot memory store",
                author=b"nanobot <nanobot@dream>",
                committer=b"nanobot <nanobot@dream>",
            )
            logger.info("Git store initialized at {}", self._workspace)
            return True
        except Exception:
            logger.exception("Git store init failed for {}", self._workspace)
            return False

    # -- daily operations ------------------------------------------------------

    def auto_commit(self, message: str) -> str | None:
        """Stage tracked memory files and commit if there are changes.

        Returns the short commit SHA, or None if nothing to commit.
        """
        if not self.is_initialized():
            return None

        try:
            from dulwich import porcelain

            # .gitignore excludes everything except tracked files,
            # so any staged/unstaged change must be in our files.
            st = porcelain.status(str(self._workspace))
            if not st.unstaged and not any(st.staged.values()):
                return None

            msg_bytes = message.encode("utf-8") if isinstance(message, str) else message
            porcelain.add(str(self._workspace), paths=self._tracked_files)
            sha_bytes = porcelain.commit(
                str(self._workspace),
                message=msg_bytes,
                author=b"nanobot <nanobot@dream>",
                committer=b"nanobot <nanobot@dream>",
            )
            if sha_bytes is None:
                return None
            sha = sha_bytes.hex()[:8]
            logger.debug("Git auto-commit: {} ({})", sha, message)
            return sha
        except Exception:
            logger.exception("Git auto-commit failed: {}", message)
            return None

    # -- internal helpers ------------------------------------------------------

    def _resolve_sha(self, short_sha: str) -> bytes | None:
        """Resolve a short SHA prefix to the full SHA bytes."""
        try:
            from dulwich.repo import Repo

            with Repo(str(self._workspace)) as repo:
                try:
                    sha = repo.refs[b"HEAD"]
                except KeyError:
                    return None

                while sha:
                    if sha.hex().startswith(short_sha):
                        return sha
                    commit = repo[sha]
                    if commit.type_name != b"commit":
                        break
                    sha = commit.parents[0] if commit.parents else None
            return None
        except Exception:
            return None

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
        """Generate .gitignore content from tracked files."""
        dirs: set[str] = set()
        for f in self._tracked_files:
            parent = str(Path(f).parent)
            if parent != ".":
                dirs.add(parent)
        lines = ["/*"]
        for d in sorted(dirs):
            lines.append(f"!{d}/")
        for f in self._tracked_files:
            lines.append(f"!{f}")
        lines.append("!.gitignore")
        return "\n".join(lines) + "\n"

    # -- query -----------------------------------------------------------------

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
                    head = repo.refs[b"HEAD"]
                except KeyError:
                    return []

                sha = head
                while sha and len(entries) < max_entries:
                    commit = repo[sha]
                    if commit.type_name != b"commit":
                        break
                    ts = time.strftime(
                        "%Y-%m-%d %H:%M",
                        time.localtime(commit.commit_time),
                    )
                    msg = commit.message.decode("utf-8", errors="replace").strip()
                    if message_prefix is None or msg.startswith(message_prefix):
                        entries.append(CommitInfo(
                            sha=sha.hex()[:8],
                            message=msg,
                            timestamp=ts,
                        ))
                    sha = commit.parents[0] if commit.parents else None

            return entries
        except Exception:
            logger.exception("Git log failed")
            return []

    def line_ages(self, file_path: str) -> list[LineAge]:
        """Compute the age of each line in a tracked file via git blame.

        Returns one LineAge per line, in order.
        Returns an empty list if the repo is not initialized, the file is
        empty, or annotation fails.
        """

        if not self.is_initialized():
            return []

        target = self._workspace / file_path
        if not target.exists() or target.stat().st_size == 0:
            return []

        try:
            from dulwich import porcelain

            annotated = porcelain.annotate(str(self._workspace), file_path)
        except Exception:
            logger.exception("Git line_ages annotate failed for {}", file_path)
            return []

        if not annotated:
            return []

        return _compute_line_ages(annotated)

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
        except Exception:
            logger.exception("Git diff_commits failed")
            return ""

    def summarize_working_tree(self, paths: list[str]) -> str:
        """Structured summary of working-tree changes vs HEAD for *paths*.

        Pure filesystem/git ground truth — never LLM narrative — suitable as a
        truthful audit record. Returns "" when the repo is not initialized or
        none of *paths* differ from HEAD.

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
        except ImportError:
            return ""

        summary_lines: list[str] = []
        diff_lines: list[str] = []
        total_added = 0
        total_removed = 0
        changed = 0

        try:
            with Repo(str(self._workspace)) as repo:
                head_tree = self._head_tree(repo)
                for path in paths:
                    head_text = (
                        self._read_blob_from_tree(repo, head_tree, path)
                        if head_tree is not None
                        else None
                    )
                    if head_text is None:
                        head_text = ""
                    wt_path = self._workspace / path
                    try:
                        wt_text = (
                            wt_path.read_text(encoding="utf-8")
                            if wt_path.exists()
                            else ""
                        )
                    except UnicodeDecodeError:
                        # Non-UTF-8 (binary/corrupt) working-tree file: record
                        # the change without a unified diff, which would
                        # otherwise be polluted with replacement characters and
                        # misrepresent the audit record.
                        changed += 1
                        summary_lines.append(f"{path}: binary or non-UTF-8 file changed")
                        continue
                    if head_text == wt_text:
                        continue
                    changed += 1
                    hunks = list(difflib.unified_diff(
                        head_text.splitlines(),
                        wt_text.splitlines(),
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
        except Exception:
            logger.exception("Git summarize_working_tree failed")
            return ""

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
    def _head_tree(repo) -> object | None:
        """Return the tree object at HEAD, or None if there are no commits."""
        try:
            head = repo.refs[b"HEAD"]
        except KeyError:
            return None
        commit = repo[head]
        if commit.type_name != b"commit":
            return None
        return repo[commit.tree]

    def find_commit(self, short_sha: str, max_entries: int = 20) -> CommitInfo | None:
        """Find a commit by short SHA prefix match."""
        for c in self.log(max_entries=max_entries):
            if c.sha.startswith(short_sha):
                return c
        return None

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
                        commit = repo[full_sha]
                        parent = commit.parents[0] if commit.parents else None
                    diff = self.diff_commits(parent.hex()[:8], c.sha) if parent else ""
                    return c, diff
            return None
        except Exception:
            logger.exception("Git show_commit_diff failed")
            return None

    # -- restore ---------------------------------------------------------------

    def revert(self, commit: str, *, message_prefix: str | None = None) -> str | None:
        """Revert (undo) the changes introduced by the given commit.

        Restores all tracked memory files to the state at the commit's parent,
        then creates a new commit recording the revert. When *message_prefix*
        is provided, commits outside that history are rejected before any files
        are changed.

        Returns the new commit SHA, or None on failure.
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

                commit_message = commit_obj.message.decode("utf-8", errors="replace").strip()
                if message_prefix is not None and not commit_message.startswith(message_prefix):
                    logger.warning(
                        "Git revert: commit {} does not match message prefix {!r}",
                        commit,
                        message_prefix,
                    )
                    return None

                if not commit_obj.parents:
                    logger.warning("Git revert: cannot revert root commit {}", commit)
                    return None

                # Use the parent's tree — this undoes the commit's changes
                parent_obj = repo[commit_obj.parents[0]]
                tree = repo[parent_obj.tree]

                restored: list[str] = []
                for filepath in self._tracked_files:
                    content = self._read_blob_from_tree(repo, tree, filepath)
                    if content is not None:
                        dest = self._workspace / filepath
                        dest.write_text(content, encoding="utf-8")
                        restored.append(filepath)

            if not restored:
                return None

            # Commit the restored state
            msg = f"revert: undo {commit}"
            return self.auto_commit(msg)
        except Exception:
            logger.exception("Git revert failed for {}", commit)
            return None

    @staticmethod
    def _read_blob_from_tree(repo, tree, filepath: str) -> str | None:
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
                return obj.data.decode("utf-8", errors="replace")
            if obj.type_name == b"tree":
                current = obj
            else:
                return None
        return None
