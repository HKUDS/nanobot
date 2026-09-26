"""Tests for GitStore core operations."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.utils.gitstore import GitStore, GitStoreError


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


class TestRuntimeFileIgnoring:
    """Regression tests for GitHub issue #5246.

    Runtime files created inside tracked directories (memory/history.jsonl,
    memory/.cursor) must not show up as untracked in the workspace repo.
    """

    TRACKED = ["SOUL.md", "USER.md", "memory/MEMORY.md", "memory/.dream_cursor"]

    def test_new_workspace_ignores_runtime_files(self, tmp_path):
        g = GitStore(tmp_path, tracked_files=self.TRACKED)
        g.init()
        (tmp_path / "memory" / "history.jsonl").write_text("{}\n", encoding="utf-8")
        (tmp_path / "memory" / ".cursor").write_text("0", encoding="utf-8")
        status = subprocess.run(
            ["git", "-C", str(tmp_path), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "history.jsonl" not in status
        assert ".cursor" not in status

    def test_tracked_files_remain_unignored(self, tmp_path):
        g = GitStore(tmp_path, tracked_files=self.TRACKED)
        g.init()
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "check-ignore", "memory/MEMORY.md", "SOUL.md"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1  # exit 1: no path ignored

    def test_ensure_gitignore_backfills_legacy_workspace(self, tmp_path):
        from dulwich import porcelain

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        porcelain.init(str(workspace))
        legacy = "/*\n!memory/\n!SOUL.md\n!USER.md\n!memory/MEMORY.md\n!.gitignore\n"
        (workspace / ".gitignore").write_text(legacy, encoding="utf-8")

        g = GitStore(workspace, tracked_files=self.TRACKED)
        assert g.ensure_gitignore() is True

        lines = (workspace / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert "memory/*" in lines
        ignore_idx = lines.index("memory/*")
        # Negations must follow the ignore rule to keep tracked files visible.
        last_negations = {
            line: idx for idx, line in enumerate(lines) if line.startswith("!memory/")
        }
        assert last_negations["!memory/MEMORY.md"] > ignore_idx
        assert last_negations["!memory/.dream_cursor"] > ignore_idx
        assert legacy.strip() in "\n".join(lines)  # legacy content preserved
        assert g.ensure_gitignore() is False  # idempotent

        memory_dir = workspace / "memory"
        memory_dir.mkdir(exist_ok=True)
        (memory_dir / "history.jsonl").write_text("{}\n", encoding="utf-8")
        result = subprocess.run(
            ["git", "-C", str(workspace), "check-ignore", "memory/history.jsonl"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_ensure_gitignore_noop_when_not_initialized(self, tmp_path):
        g = GitStore(tmp_path, tracked_files=self.TRACKED)
        assert g.ensure_gitignore() is False
        assert not (tmp_path / ".gitignore").exists()

    @pytest.mark.parametrize("fresh", [False, True])
    def test_user_unignore_keeps_precedence(self, tmp_path, fresh):
        from dulwich import porcelain

        legacy = "/*\n!memory/\n!SOUL.md\n!USER.md\n!memory/MEMORY.md\n!.gitignore\n"
        custom = "# Keep project notes\n!memory/team-notes.md\n"
        ignore = tmp_path / ".gitignore"
        ignore.write_text(legacy + custom, encoding="utf-8")
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory/team-notes.md").write_text("user notes", encoding="utf-8")
        store = GitStore(tmp_path, tracked_files=self.TRACKED)
        if fresh:
            store.init()
        else:
            porcelain.init(str(tmp_path))
            assert store.ensure_gitignore()
        assert ignore.read_text(encoding="utf-8").endswith(custom)
        assert not store.ensure_gitignore()
        result = subprocess.run(
            ["git", "-C", str(tmp_path), "check-ignore", "memory/team-notes.md"],
            capture_output=True,
        )
        assert result.returncode == 1
        assert (tmp_path / "memory/team-notes.md").read_text() == "user notes"

    @pytest.mark.parametrize("existing", [None, "*.pyc\n", "/*\n!memory/\n!memory/team-notes.md\n!.gitignore\n"])
    def test_unknown_user_policy_is_not_migrated(self, tmp_path, existing):
        from dulwich import porcelain

        porcelain.init(str(tmp_path))
        ignore = tmp_path / ".gitignore"
        if existing is not None:
            ignore.write_text(existing, encoding="utf-8")
        assert not GitStore(tmp_path, tracked_files=self.TRACKED).ensure_gitignore()
        assert (ignore.read_text(encoding="utf-8") if ignore.exists() else None) == existing

    def test_failed_replace_preserves_legacy_file_and_can_retry(self, tmp_path, monkeypatch):
        from dulwich import porcelain

        porcelain.init(str(tmp_path))
        legacy = "/*\n!memory/\n!SOUL.md\n!USER.md\n!memory/MEMORY.md\n!.gitignore\n"
        ignore = tmp_path / ".gitignore"
        ignore.write_text(legacy, encoding="utf-8")
        store = GitStore(tmp_path, tracked_files=self.TRACKED)
        with monkeypatch.context() as m:
            def denied(*args):
                raise PermissionError("read-only workspace")
            m.setattr(Path, "replace", denied)
            with pytest.raises(GitStoreError):
                store.ensure_gitignore()
        assert ignore.read_text(encoding="utf-8") == legacy
        assert not list(tmp_path.glob("..gitignore.*.tmp"))
        assert store.ensure_gitignore()

    def test_symlinked_ignore_policy_is_not_migrated(self, tmp_path):
        from dulwich import porcelain

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        porcelain.init(str(workspace))
        target = tmp_path / "shared-ignore"
        legacy = b"/*\n!memory/\n!SOUL.md\n!USER.md\n!memory/MEMORY.md\n!.gitignore\n"
        target.write_bytes(legacy)
        ignore = workspace / ".gitignore"
        try:
            ignore.symlink_to(target)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")

        assert not GitStore(workspace, tracked_files=self.TRACKED).ensure_gitignore()
        assert ignore.is_symlink()
        assert target.read_bytes() == legacy

    def test_migration_does_not_untrack_existing_runtime_files(self, tmp_path):
        store = GitStore(tmp_path, tracked_files=self.TRACKED)
        store.init()
        (tmp_path / "memory/history.jsonl").write_text("{}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "-f", "memory/history.jsonl"], check=True)
        (tmp_path / ".gitignore").write_text(
            "/*\n!memory/\n!SOUL.md\n!USER.md\n!memory/MEMORY.md\n!.gitignore\n",
            encoding="utf-8",
        )
        assert store.ensure_gitignore()
        assert b"memory/history.jsonl" in subprocess.run(
            ["git", "-C", str(tmp_path), "ls-files"], capture_output=True, check=True,
        ).stdout
