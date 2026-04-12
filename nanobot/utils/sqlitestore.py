"""SQLite-backed version control for memory files."""

from __future__ import annotations

import json
import random
import sqlite3
import string
import time
from difflib import unified_diff
from pathlib import Path

from loguru import logger

from nanobot.utils.version_store import CommitInfo


class SQLiteStore:
    """SQLite-backed version control for memory files.

    API-compatible with GitStore but uses SQLite for storage,
    avoiding conflicts with user's own git repository.
    """

    def __init__(self, workspace: Path, tracked_files: list[str]):
        self._workspace = workspace
        self._tracked_files = tracked_files
        self._db_path = workspace / "memory" / ".dream_history.db"

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        """Create the commits table if it doesn't exist."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    snapshots TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sha ON commits(sha)")

    def is_initialized(self) -> bool:
        """Check if the database has been initialized."""
        return self._db_path.exists()

    # -- init ------------------------------------------------------------------

    def init(self) -> bool:
        """Initialize the SQLite store.

        Creates the database table and makes an initial commit.
        Returns True if a new store was created, False if already exists.
        """
        if self.is_initialized():
            return False

        try:
            self._ensure_table()
            # Touch tracked files if missing
            for rel in self._tracked_files:
                p = self._workspace / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_text("", encoding="utf-8")
            logger.info("SQLite store initialized at {}", self._db_path)
            return True
        except Exception:
            logger.warning("SQLite store init failed for {}", self._workspace)
            return False

    # -- daily operations ------------------------------------------------------

    def _read_snapshots(self) -> dict[str, str]:
        """Read current content of all tracked files."""
        snapshots: dict[str, str] = {}
        for rel in self._tracked_files:
            p = self._workspace / rel
            try:
                snapshots[rel] = p.read_text(encoding="utf-8")
            except FileNotFoundError:
                snapshots[rel] = ""
        return snapshots

    def _generate_sha(self) -> str:
        """Generate a random 8-character ID."""
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))

    def auto_commit(self, message: str) -> str | None:
        """Record current state of tracked files if there are changes.

        Returns the commit SHA, or None if nothing to commit.
        """
        if not self.is_initialized():
            # Auto-initialize on first use
            self.init()

        try:
            self._ensure_table()
            snapshots = self._read_snapshots()

            # Check if anything changed from last commit
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT snapshots FROM commits ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    last_snapshots = json.loads(row["snapshots"])
                    if snapshots == last_snapshots:
                        return None

            sha = self._generate_sha()
            ts = time.strftime("%Y-%m-%d %H:%M")
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO commits (sha, message, timestamp, snapshots) VALUES (?, ?, ?, ?)",
                    (sha, message, ts, json.dumps(snapshots, ensure_ascii=False)),
                )
            logger.debug("SQLite auto-commit: {} ({})", sha, message)
            return sha
        except Exception:
            logger.warning("SQLite auto-commit failed: {}", message)
            return None

    # -- query -----------------------------------------------------------------

    def log(self, max_entries: int = 20) -> list[CommitInfo]:
        """Return commit log, most recent first."""
        if not self.is_initialized():
            return []

        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT sha, message, timestamp FROM commits ORDER BY id DESC LIMIT ?",
                    (max_entries,),
                ).fetchall()
            return [CommitInfo(sha=r["sha"], message=r["message"], timestamp=r["timestamp"]) for r in rows]
        except Exception:
            logger.warning("SQLite log failed")
            return []

    def find_commit(self, short_sha: str, max_entries: int = 20) -> CommitInfo | None:
        """Find a commit by SHA prefix match."""
        for c in self.log(max_entries=max_entries):
            if c.sha.startswith(short_sha):
                return c
        return None

    def _get_snapshots_by_sha(self, sha: str) -> dict[str, str] | None:
        """Get snapshots for a commit by SHA."""
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT snapshots FROM commits WHERE sha = ?",
                    (sha,),
                ).fetchone()
                if row:
                    return json.loads(row["snapshots"])
        except Exception:
            pass
        return None

    def _compute_diff(self, old_snapshots: dict[str, str] | None, new_snapshots: dict[str, str]) -> str:
        """Compute unified diff between two snapshot sets."""
        diffs: list[str] = []
        all_files = set(old_snapshots or {}) | set(new_snapshots)
        for filepath in sorted(all_files):
            old_content = (old_snapshots or {}).get(filepath, "")
            new_content = new_snapshots.get(filepath, "")
            if old_content == new_content:
                continue
            old_lines = old_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            diff_lines = list(unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{filepath}",
                tofile=f"b/{filepath}",
            ))
            if diff_lines:
                diffs.append("".join(diff_lines))
        return "\n".join(diffs)

    def show_commit_diff(self, short_sha: str, max_entries: int = 20) -> tuple[CommitInfo, str] | None:
        """Find a commit and return it with its diff vs the parent."""
        commits = self.log(max_entries=max_entries)
        for i, c in enumerate(commits):
            if c.sha.startswith(short_sha):
                new_snapshots = self._get_snapshots_by_sha(c.sha)
                if new_snapshots is None:
                    return None
                # Get parent snapshots
                old_snapshots: dict[str, str] | None = None
                if i + 1 < len(commits):
                    old_snapshots = self._get_snapshots_by_sha(commits[i + 1].sha)
                diff = self._compute_diff(old_snapshots, new_snapshots)
                return c, diff
        return None

    # -- restore ---------------------------------------------------------------

    def revert(self, commit: str) -> str | None:
        """Revert (undo) the changes introduced by the given commit.

        Restores all tracked memory files to the state at the commit's parent,
        then creates a new commit recording the revert.

        Returns the new commit SHA, or None on failure.
        """
        if not self.is_initialized():
            return None

        try:
            commits = self.log(max_entries=100)
            for i, c in enumerate(commits):
                if c.sha.startswith(commit):
                    if i + 1 >= len(commits):
                        logger.warning("SQLite revert: cannot revert oldest commit {}", commit)
                        return None
                    # Restore parent's snapshots
                    parent_snapshots = self._get_snapshots_by_sha(commits[i + 1].sha)
                    if parent_snapshots is None:
                        return None
                    for filepath, content in parent_snapshots.items():
                        p = self._workspace / filepath
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(content, encoding="utf-8")
                    # Commit the revert
                    msg = f"revert: undo {commit}"
                    return self.auto_commit(msg)
            logger.warning("SQLite revert: SHA not found: {}", commit)
            return None
        except Exception:
            logger.warning("SQLite revert failed for {}", commit)
            return None

    # -- migration -------------------------------------------------------------

    def migrate_from_git(self) -> int:
        """Migrate dream history from GitStore to SQLiteStore.

        Reads all commits from the existing git repository and replays them
        into SQLite. Returns the number of commits migrated.

        This is a one-time migration for users switching from git to sqlite backend.
        """
        from nanobot.utils.gitstore import GitStore

        git_store = GitStore(self._workspace, tracked_files=self._tracked_files)
        if not git_store.is_initialized():
            logger.info("No git store found, skipping migration")
            return 0

        if self.is_initialized():
            logger.warning("SQLite store already exists, skipping migration")
            return 0

        try:
            # Read all commits from git (oldest first for correct ordering)
            git_commits = git_store.log(max_entries=1000)
            if not git_commits:
                logger.info("No git commits to migrate")
                return 0

            # Reverse to get oldest first
            git_commits = list(reversed(git_commits))

            # Initialize SQLite store
            self._ensure_table()

            migrated = 0
            for commit in git_commits:
                # Get file snapshots at this commit using dulwich
                snapshots = self._read_git_snapshots_at_commit(commit.sha)
                if snapshots is None:
                    logger.warning("Failed to read snapshots for git commit {}", commit.sha)
                    continue

                # Insert into SQLite
                with self._get_conn() as conn:
                    conn.execute(
                        "INSERT INTO commits (sha, message, timestamp, snapshots) VALUES (?, ?, ?, ?)",
                        (commit.sha, commit.message, commit.timestamp, json.dumps(snapshots, ensure_ascii=False)),
                    )
                migrated += 1

            logger.info("Migrated {} commits from git to SQLite", migrated)
            return migrated
        except Exception:
            logger.exception("Git to SQLite migration failed")
            return 0

    def _read_git_snapshots_at_commit(self, short_sha: str) -> dict[str, str] | None:
        """Read file snapshots at a specific git commit."""
        try:
            from dulwich.repo import Repo

            with Repo(str(self._workspace)) as repo:
                # Resolve short SHA to full SHA
                try:
                    head = repo.refs[b"HEAD"]
                except KeyError:
                    return None

                full_sha = None
                sha = head
                while sha:
                    if sha.hex().startswith(short_sha):
                        full_sha = sha
                        break
                    commit = repo[sha]
                    if commit.type_name != b"commit":
                        break
                    sha = commit.parents[0] if commit.parents else None

                if not full_sha:
                    return None

                # Read files from the commit's tree
                commit_obj = repo[full_sha]
                if commit_obj.type_name != b"commit":
                    return None

                tree = repo[commit_obj.tree]
                snapshots: dict[str, str] = {}

                for filepath in self._tracked_files:
                    content = self._read_blob_from_tree(repo, tree, filepath)
                    if content is not None:
                        snapshots[filepath] = content

                return snapshots
        except Exception:
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
