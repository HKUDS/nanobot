"""Tests for GitStore core operations."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.utils.gitstore import GitStore


@pytest.fixture
def git(tmp_path):
    """Create an initialized GitStore with tracked MEMORY.md."""
    g = GitStore(tmp_path, tracked_files=["MEMORY.md", "SOUL.md"])
    g.init()
    return g


class TestSummarizeWorkingTree:
    """Ground-truth diff summary used to keep Dream audit records honest."""

    def test_empty_when_not_initialized(self, tmp_path):
        git = GitStore(tmp_path, tracked_files=["MEMORY.md"])
        assert git.summarize_working_tree(["MEMORY.md"]) == ""

    def test_empty_when_no_changes(self, git):
        assert git.summarize_working_tree(["MEMORY.md", "SOUL.md"]) == ""

    def test_summarizes_real_change(self, git, tmp_path):
        (tmp_path / "MEMORY.md").write_text("# Memory\n- new fact\n", encoding="utf-8")
        summary = git.summarize_working_tree(["MEMORY.md"])
        assert "MEMORY.md: +2 -0" in summary
        assert "new fact" in summary
        assert "1 file changed, 2 insertions(+), 0 deletions(-)" in summary

    def test_only_reports_requested_paths(self, git, tmp_path):
        # MEMORY.md changes, but we only ask about the unchanged SOUL.md.
        (tmp_path / "MEMORY.md").write_text("changed\n", encoding="utf-8")
        assert git.summarize_working_tree(["SOUL.md"]) == ""

    def test_counts_additions_and_removals(self, git, tmp_path):
        (tmp_path / "MEMORY.md").write_text("# M\n- keep\n- new\n", encoding="utf-8")
        summary = git.summarize_working_tree(["MEMORY.md"])
        assert "MEMORY.md: +3 -0" in summary

    def test_detects_deletion(self, git, tmp_path):
        # File removed from the working tree (must have content first; the
        # fixture's tracked files start empty, so an empty-file delete is a no-op).
        (tmp_path / "MEMORY.md").write_text("has content\n", encoding="utf-8")
        git.auto_commit("add content")
        (tmp_path / "MEMORY.md").unlink()
        summary = git.summarize_working_tree(["MEMORY.md"])
        assert summary  # a removal is still a change
        assert "deletion" in summary

    def test_non_utf8_file_marked_binary_without_replacement_chars(self, git, tmp_path):
        # Invalid UTF-8 must not leak replacement chars into the audit record.
        (tmp_path / "MEMORY.md").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01")
        summary = git.summarize_working_tree(["MEMORY.md"])
        assert "MEMORY.md: binary or non-UTF-8 file changed" in summary
        assert "\ufffd" not in summary  # no U+FFFD replacement chars leaked


class TestNestedRepoProtection:
    """Regression tests for GitHub issue #2980: nested repo protection."""

    def test_init_refuses_inside_git_repo(self, tmp_path):
        """init() should detect it's inside an existing git repo and refuse."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".git").mkdir()

        workspace = project / "workspace"
        workspace.mkdir()

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is False
        assert not (workspace / ".git").is_dir()

    def test_init_preserves_existing_gitignore(self, tmp_path):
        """init() should preserve existing .gitignore entries and append new ones."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        existing = "*.pyc\n__pycache__/\n"
        (workspace / ".gitignore").write_text(existing, encoding="utf-8")

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is True
        gitignore = (workspace / ".gitignore").read_text(encoding="utf-8")
        assert "*.pyc" in gitignore
        assert "__pycache__/" in gitignore
        assert "!MEMORY.md" in gitignore
        assert "!.gitignore" in gitignore

    def test_init_no_gitignore_creates_new(self, tmp_path):
        """init() should create .gitignore with Dream content when none exists."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is True
        gitignore = (workspace / ".gitignore").read_text(encoding="utf-8")
        expected = g._build_gitignore()
        assert gitignore == expected

    def test_init_gitignore_merge_idempotent(self, tmp_path):
        """init() should not duplicate Dream entries already in .gitignore."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Pre-existing .gitignore that already has some Dream entries
        existing = "*.pyc\n/*\n!MEMORY.md\n"
        (workspace / ".gitignore").write_text(existing, encoding="utf-8")

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is True
        gitignore = (workspace / ".gitignore").read_text(encoding="utf-8")
        # No duplicate lines
        lines = gitignore.splitlines()
        assert lines.count("/*") == 1
        assert lines.count("!MEMORY.md") == 1
        # Existing entry preserved, new Dream entries appended
        assert "*.pyc" in gitignore
        assert "!.gitignore" in gitignore

    def test_init_outside_git_repo_works_normally(self, tmp_path):
        """init() should succeed and create .git when not inside a git repo."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is True
        assert (workspace / ".git").is_dir()

    def test_staging_paths_are_absolute_from_workspace(self, tmp_path, monkeypatch):
        """Git operations should not depend on the process working directory."""
        from dulwich import porcelain

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(tmp_path)

        git = GitStore(workspace, tracked_files=["MEMORY.md"])

        with patch.object(porcelain, "add", wraps=porcelain.add) as mock_add:
            assert git.init() is True
            assert len(git.log()) == 1

            (workspace / "MEMORY.md").write_text("updated\n", encoding="utf-8")
            assert git.auto_commit("update memory") is not None
            assert len(git.log()) == 2

        assert len(mock_add.call_args_list) == 2
        for call in mock_add.call_args_list:
            staging_paths = [Path(path) for path in call.kwargs["paths"]]
            assert all(path.is_absolute() for path in staging_paths)
            assert all(path.is_relative_to(workspace) for path in staging_paths)

    def test_staging_paths_preserve_symlinks(self, tmp_path):
        """Absolute staging paths should still identify the tracked symlink itself."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = tmp_path / "shared-memory.md"
        target.write_text("shared\n", encoding="utf-8")
        link = workspace / "MEMORY.md"
        try:
            link.symlink_to(target)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")

        git = GitStore(workspace, tracked_files=["MEMORY.md"])

        staging_path = Path(git._staging_paths("MEMORY.md")[0])
        assert staging_path == link.absolute()
        assert staging_path.is_symlink()

    def test_init_refuses_inside_git_worktree(self, tmp_path):
        """init() should refuse when the parent checkout is a git worktree."""
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "README.md").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "-q",
                "-m",
                "init",
            ],
            check=True,
        )
        subprocess.run(["git", "-C", str(repo), "branch", "wt-branch"], check=True)

        worktree = tmp_path / "worktree"
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-q", str(worktree), "wt-branch"],
            check=True,
        )
        assert (worktree / ".git").is_file()

        workspace = worktree / "workspace"
        workspace.mkdir()

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is False
        assert not (workspace / ".git").exists()


class TestCommitIdEncoding:
    """Commit ids must be usable with git, not hex-of-hex."""

    def test_auto_commit_returns_the_real_short_sha(self, git, tmp_path):
        (tmp_path / "MEMORY.md").write_text("- a fact\n", encoding="utf-8")
        sha = git.auto_commit("memory update")
        expected = subprocess.run(
            ["git", "-C", str(tmp_path), "log", "-1", "--format=%h", "--abbrev=8"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert sha == expected

    def test_a_real_git_sha_resolves(self, git, tmp_path):
        (tmp_path / "MEMORY.md").write_text("- a fact\n", encoding="utf-8")
        git.auto_commit("memory update")
        real = subprocess.run(
            ["git", "-C", str(tmp_path), "log", "-1", "--format=%h", "--abbrev=8"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert git._resolve_sha(real) is not None
