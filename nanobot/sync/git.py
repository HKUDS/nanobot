"""Git-backed workspace sync.

Commits selected workspace changes (memory consolidation, identity edits) to
a git repo at the workspace root, with optional push to a remote. Auth uses
whatever the host git is configured with — we just shell out.

Design notes in vault/sketches/p1-auto-commit-nanobot.md.
"""

from __future__ import annotations

import asyncio
import socket
import time
from collections import deque
from pathlib import Path

from loguru import logger

from nanobot.config.schema import SyncConfig


class WorkspaceSync:
    """Async wrapper around git subprocess for workspace sync."""

    def __init__(self, workspace: Path, config: SyncConfig):
        self.workspace = Path(workspace).expanduser()
        self.config = config
        self._lock = asyncio.Lock()
        self._commit_times: deque[float] = deque()
        self._initialised = self._detect_git()
        if config.enabled and not self._initialised:
            logger.warning(
                "Workspace sync enabled but {} is not a git repo. "
                "Run `git init` and configure a remote to enable sync.",
                self.workspace,
            )

    @property
    def active(self) -> bool:
        """True when sync should attempt git operations."""
        return self.config.enabled and self._initialised

    @property
    def branch(self) -> str:
        """Effective remote branch name.

        Default is the configured branch (typically "main" — bots commit
        straight to main, humans revert via git if needed). An empty
        config value falls back to a per-host branch as an opt-in for
        users who want a review gate.
        """
        if self.config.branch:
            return self.config.branch
        host = socket.gethostname().split(".", 1)[0]
        return f"host/{host}"

    async def commit(self, reason: str) -> bool:
        """Stage all tracked changes and create a commit.

        Returns True if a commit was made, False otherwise (clean tree,
        throttled, sync disabled, or git error).
        """
        if not self.active:
            return False
        async with self._lock:
            if self._is_throttled():
                logger.info("Workspace sync: throttled, skipping commit ({})", reason)
                return False
            try:
                if not await self._has_changes():
                    return False
                await self._run("git", "add", "-A")
                if not await self._has_staged_changes():
                    return False
                env = self._git_author_env()
                await self._run(
                    "git", "commit", "-m", reason,
                    env=env,
                )
                self._commit_times.append(time.monotonic())
                logger.info("Workspace sync: committed ({})", reason)
                if self.config.push:
                    await self._push_locked()
                return True
            except _GitError as e:
                logger.warning("Workspace sync: git error during commit ({}): {}", reason, e)
                return False

    async def push(self) -> bool:
        """Push the configured branch to the configured remote."""
        if not self.active:
            return False
        async with self._lock:
            try:
                return await self._push_locked()
            except _GitError as e:
                logger.warning("Workspace sync: push failed: {}", e)
                return False

    async def shutdown(self, reason: str = "shutdown: pending changes") -> bool:
        """Commit any pending state and push. Called from gateway finally block."""
        if not (self.active and self.config.commit_on_shutdown):
            return False
        return await self.commit(reason)

    # ---- internals ----

    def _detect_git(self) -> bool:
        return (self.workspace / ".git").exists()

    def _git_author_env(self) -> dict[str, str]:
        import os
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = self.config.author_name
        env["GIT_AUTHOR_EMAIL"] = self.config.author_email
        env["GIT_COMMITTER_NAME"] = self.config.author_name
        env["GIT_COMMITTER_EMAIL"] = self.config.author_email
        return env

    def _is_throttled(self) -> bool:
        cap = self.config.max_commits_per_hour
        if cap <= 0:
            return False
        cutoff = time.monotonic() - 3600.0
        while self._commit_times and self._commit_times[0] < cutoff:
            self._commit_times.popleft()
        return len(self._commit_times) >= cap

    async def _has_changes(self) -> bool:
        """True if working tree has any modifications (tracked or untracked)."""
        out = await self._run("git", "status", "--porcelain")
        return bool(out.strip())

    async def _has_staged_changes(self) -> bool:
        """True if the index differs from HEAD (i.e. `git commit` would succeed)."""
        try:
            await self._run("git", "diff", "--cached", "--quiet")
            return False  # exit 0 → no diff
        except _GitError as e:
            if e.returncode == 1:
                return True  # exit 1 → diff present
            raise

    async def _push_locked(self) -> bool:
        """Push HEAD to remote:branch. Assumes caller holds the lock."""
        await self._run(
            "git", "push", self.config.remote,
            f"HEAD:refs/heads/{self.branch}",
        )
        logger.info("Workspace sync: pushed to {}/{}", self.config.remote, self.branch)
        return True

    async def _run(self, *args: str, env: dict[str, str] | None = None) -> str:
        """Run a git command in the workspace, returning stdout. Raises _GitError."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise _GitError(
                args=args,
                returncode=proc.returncode or 1,
                stderr=stderr.decode("utf-8", errors="replace").strip(),
            )
        return stdout.decode("utf-8", errors="replace")


class _GitError(Exception):
    def __init__(self, *, args: tuple[str, ...], returncode: int, stderr: str):
        self.args_run = args
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"{' '.join(args)} exited {returncode}: {stderr}")
