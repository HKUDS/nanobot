"""Tests for WorkspaceSync against a real git binary + tmp_path bare remote."""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import pytest

from nanobot.config.schema import SyncConfig
from nanobot.sync import WorkspaceSync


# ---- helpers ----

def _git(workspace: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        check=check, capture_output=True, text=True,
    )


@pytest.fixture
def workspace_with_remote(tmp_path):
    """Initialize a workspace repo + bare remote in tmp_path."""
    workspace = tmp_path / "ws"
    remote = tmp_path / "remote.git"
    workspace.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(workspace)], check=True, capture_output=True)
    # Initial commit so HEAD is valid.
    (workspace / "README.md").write_text("ws\n")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "test")
    _git(workspace, "add", "README.md")
    _git(workspace, "commit", "-m", "init")
    _git(workspace, "remote", "add", "origin", str(remote))
    return workspace, remote


def _config(**overrides) -> SyncConfig:
    defaults = dict(enabled=True, push=False, branch="host/test", remote="origin")
    defaults.update(overrides)
    return SyncConfig(**defaults)


def _remote_branch_sha(remote: Path, branch: str) -> str | None:
    res = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", f"refs/heads/{branch}"],
        capture_output=True, text=True,
    )
    return res.stdout.strip() if res.returncode == 0 else None


# ---- tests ----

@pytest.mark.asyncio
async def test_disabled_when_no_dot_git(tmp_path):
    sync = WorkspaceSync(tmp_path / "no-git", _config())
    assert not sync.active
    assert not await sync.commit("anything")


@pytest.mark.asyncio
async def test_disabled_when_config_disabled(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config(enabled=False))
    assert not sync.active


@pytest.mark.asyncio
async def test_commit_creates_commit_when_dirty(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config())
    (workspace / "MEMORY.md").write_text("first note\n")

    before = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert await sync.commit("memory: first note")
    after = _git(workspace, "rev-parse", "HEAD").stdout.strip()

    assert before != after
    msg = _git(workspace, "log", "-1", "--pretty=%s").stdout.strip()
    assert msg == "memory: first note"


@pytest.mark.asyncio
async def test_commit_is_noop_when_clean(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config())
    before = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert not await sync.commit("nothing to do")
    after = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert before == after


@pytest.mark.asyncio
async def test_commit_author_uses_config(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config(
        author_name="peewee", author_email="peewee@nanobot.local"
    ))
    (workspace / "MEMORY.md").write_text("x\n")
    assert await sync.commit("memory: x")
    author = _git(workspace, "log", "-1", "--pretty=%an <%ae>").stdout.strip()
    assert author == "peewee <peewee@nanobot.local>"


@pytest.mark.asyncio
async def test_push_updates_remote_branch(workspace_with_remote):
    workspace, remote = workspace_with_remote
    sync = WorkspaceSync(workspace, _config(push=True, branch="host/test"))
    (workspace / "MEMORY.md").write_text("pushed\n")

    assert _remote_branch_sha(remote, "host/test") is None
    assert await sync.commit("memory: push test")
    sha = _remote_branch_sha(remote, "host/test")
    assert sha is not None
    local = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert sha == local


@pytest.mark.asyncio
async def test_throttle_drops_excess(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config(max_commits_per_hour=2))
    for i in range(3):
        (workspace / "MEMORY.md").write_text(f"v{i}\n")
        committed = await sync.commit(f"memory: v{i}")
        if i < 2:
            assert committed, f"commit {i} should succeed"
        else:
            assert not committed, "third commit should be throttled"


@pytest.mark.asyncio
async def test_throttle_zero_disables(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config(max_commits_per_hour=0))
    for i in range(5):
        (workspace / "MEMORY.md").write_text(f"v{i}\n")
        assert await sync.commit(f"memory: v{i}")


@pytest.mark.asyncio
async def test_branch_defaults_to_hostname(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config(branch=""))
    assert sync.branch.startswith("host/")


@pytest.mark.asyncio
async def test_shutdown_commits_pending_state(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config())
    (workspace / "MEMORY.md").write_text("last words\n")
    before = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert await sync.shutdown("shutdown")
    after = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    assert after != before


@pytest.mark.asyncio
async def test_shutdown_respects_commit_on_shutdown_false(workspace_with_remote):
    workspace, _ = workspace_with_remote
    sync = WorkspaceSync(workspace, _config(commit_on_shutdown=False))
    (workspace / "MEMORY.md").write_text("should not commit\n")
    assert not await sync.shutdown("shutdown")
