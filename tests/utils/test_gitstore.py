import os
import shutil
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
        (tmp_path / "MEMORY.md").write_text("changed\n", encoding="utf-8")
        assert git.summarize_working_tree(["SOUL.md"]) == ""

    def test_counts_additions_and_removals(self, git, tmp_path):
        (tmp_path / "MEMORY.md").write_text("# M\n- keep\n- new\n", encoding="utf-8")
        summary = git.summarize_working_tree(["MEMORY.md"])
        assert "MEMORY.md: +3 -0" in summary

    def test_detects_deletion(self, git, tmp_path):
        (tmp_path / "MEMORY.md").write_text("has content\n", encoding="utf-8")
        git.auto_commit("add content")
        (tmp_path / "MEMORY.md").unlink()
        summary = git.summarize_working_tree(["MEMORY.md"])
        assert summary
        assert "deletion" in summary

    def test_non_utf8_file_marked_binary_without_replacement_chars(self, git, tmp_path):
        (tmp_path / "MEMORY.md").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01")
        summary = git.summarize_working_tree(["MEMORY.md"])
        assert "MEMORY.md: binary or non-UTF-8 file changed" in summary
        assert "\ufffd" not in summary


class TestNestedRepoProtection:
    """Regression tests for GitHub issue #2980: nested repo protection."""

    def test_init_refuses_inside_git_repo(self, tmp_path):
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
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is True
        gitignore = (workspace / ".gitignore").read_text(encoding="utf-8")
        expected = g._build_gitignore()
        assert gitignore == expected

    def test_init_gitignore_merge_idempotent(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        existing = "*.pyc\n/*\n!MEMORY.md\n"
        (workspace / ".gitignore").write_text(existing, encoding="utf-8")

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is True
        gitignore = (workspace / ".gitignore").read_text(encoding="utf-8")
        lines = gitignore.splitlines()
        assert lines.count("/*") == 1
        assert lines.count("!MEMORY.md") == 1
        assert "*.pyc" in gitignore
        assert "!.gitignore" in gitignore

    def test_init_outside_git_repo_works_normally(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        g = GitStore(workspace, tracked_files=["MEMORY.md"])
        result = g.init()

        assert result is True
        assert (workspace / ".git").is_dir()

    def test_staging_paths_are_absolute_from_workspace(self, tmp_path, monkeypatch):
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


def _git_output(workspace, *args):
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _write_page(workspace, relative, content):
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def wiki_git(tmp_path):
    git = GitStore(
        tmp_path,
        tracked_files=["SOUL.md", "USER.md", "memory/MEMORY.md", "memory/.dream_cursor"],
        tracked_dirs=["memory/wiki"],
    )
    git.init()
    return git


class TestTrackedDirectories:

    def test_init_tracks_existing_nested_pages_but_not_siblings(self, tmp_path):
        _write_page(tmp_path, "memory/wiki/topics/start.md", "# Starting point\n")
        _write_page(tmp_path, "memory/history.jsonl", "synthetic journal\n")
        _write_page(tmp_path, "memory/wiki-other/private.md", "not a wiki page\n")
        git = GitStore(tmp_path, tracked_files=["SOUL.md"], tracked_dirs=["memory/wiki"])

        assert git.init() is True
        assert set(_git_output(tmp_path, "ls-tree", "-r", "--name-only", "HEAD").splitlines()) == {
            ".gitignore", "SOUL.md", "memory/wiki/topics/start.md",
        }
        assert _git_output(tmp_path, "check-ignore", "memory/history.jsonl") == "memory/history.jsonl"
        assert git.auto_commit("no changes") is None

    def test_nested_add_change_delete_and_rename_are_audited_and_committed(self, wiki_git, tmp_path):
        changed = _write_page(tmp_path, "memory/wiki/topic.md", "old topic\n")
        renamed = _write_page(tmp_path, "memory/wiki/topics/old.md", "stable page\n")
        deleted = _write_page(tmp_path, "memory/wiki/obsolete.md", "obsolete page\n")
        first = wiki_git.auto_commit("dream: first wiki")
        assert first is not None

        changed.write_text("new topic\n", encoding="utf-8")
        renamed.rename(renamed.with_name("renamed.md"))
        deleted.unlink()
        _write_page(tmp_path, "memory/wiki/deep/new/page.md", "new page\n")
        (tmp_path / "memory/.dream_cursor").write_text("cursor only\n", encoding="utf-8")
        _write_page(tmp_path, "memory/history.jsonl", "private synthetic history\n")
        _write_page(tmp_path, "memory/wiki-other/private.md", "outside wiki\n")

        summary = wiki_git.summarize_working_tree(
            ["SOUL.md", "USER.md", "memory/MEMORY.md"], directories=["memory/wiki"],
        )
        for line in [
            "memory/wiki/topic.md: +1 -1",
            "memory/wiki/topics/old.md: +0 -1",
            "memory/wiki/topics/renamed.md: +1 -0",
            "memory/wiki/obsolete.md: +0 -1",
            "memory/wiki/deep/new/page.md: +1 -0",
        ]:
            assert line in summary
        assert "5 files changed" in summary
        assert "cursor only" not in summary
        assert "history.jsonl" not in summary
        assert "wiki-other" not in summary
        assert wiki_git.summarize_working_tree(["SOUL.md"]) == ""

        second = wiki_git.auto_commit("dream: revise wiki")
        assert second is not None
        changes = _git_output(
            tmp_path, "diff", "--name-status", "--no-renames", first, second, "--", "memory/wiki",
        )
        assert set(changes.splitlines()) == {
            "M\tmemory/wiki/topic.md",
            "D\tmemory/wiki/topics/old.md",
            "A\tmemory/wiki/topics/renamed.md",
            "D\tmemory/wiki/obsolete.md",
            "A\tmemory/wiki/deep/new/page.md",
        }
        diff = wiki_git.diff_commits(first, second)
        assert "+new topic" in diff
        assert "memory/wiki/topics/old.md" in diff
        assert "memory/wiki/topics/renamed.md" in diff
        assert _git_output(tmp_path, "show", "HEAD:memory/.dream_cursor") == "cursor only"
        tracked = _git_output(tmp_path, "ls-tree", "-r", "--name-only", "HEAD")
        assert "history.jsonl" not in tracked
        assert "wiki-other" not in tracked
        assert wiki_git.summarize_working_tree([], directories=["memory/wiki"]) == ""
        assert wiki_git.auto_commit("unchanged") is None

    def test_revert_restores_selected_parent_not_just_tip_changes(self, wiki_git, tmp_path):
        _write_page(tmp_path, "memory/MEMORY.md", "baseline memory\n")
        _write_page(tmp_path, "memory/wiki/start.md", "baseline wiki\n")
        nested = _write_page(tmp_path, "memory/wiki/topics/deleted.md", "restore me\n")
        renamed = _write_page(tmp_path, "memory/wiki/rename.md", "original name\n")
        before = wiki_git.auto_commit("dream: baseline")
        assert before is not None

        nested.unlink()
        nested.parent.rmdir()
        renamed.rename(renamed.with_name("renamed.md"))
        _write_page(tmp_path, "memory/wiki/start.md", "revised wiki\n")
        _write_page(tmp_path, "memory/wiki/added.md", "new page\n")
        _write_page(tmp_path, "memory/MEMORY.md", "revised memory\n")
        selected = wiki_git.auto_commit("dream: selected")
        assert selected is not None
        _write_page(tmp_path, "memory/wiki/later.md", "later committed page\n")
        assert wiki_git.auto_commit("dream: later") is not None

        assert wiki_git.revert(selected) is not None
        assert nested.read_text(encoding="utf-8") == "restore me\n"
        assert renamed.read_text(encoding="utf-8") == "original name\n"
        for name in ["added.md", "renamed.md", "later.md"]:
            assert not (tmp_path / "memory/wiki" / name).exists()
        assert (tmp_path / "memory/MEMORY.md").read_text(encoding="utf-8") == "baseline memory\n"
        assert _git_output(tmp_path, "diff", "--exit-code", before, "HEAD") == ""

    def test_deleted_directory_is_committed_and_restored_with_missing_parents(self, wiki_git, tmp_path):
        page = _write_page(tmp_path, "memory/wiki/deep/topic.md", "nested page\n")
        _write_page(tmp_path, "memory/MEMORY.md", "fixed memory\n")
        assert wiki_git.auto_commit("dream: populate") is not None
        shutil.rmtree(tmp_path / "memory")

        assert "memory/wiki/deep/topic.md: +0 -1" in wiki_git.summarize_working_tree(
            [], directories=["memory/wiki"],
        )
        deleted = wiki_git.auto_commit("dream: remove directory")
        assert deleted is not None
        assert "memory/" not in _git_output(tmp_path, "ls-tree", "-r", "--name-only", "HEAD")

        assert wiki_git.revert(deleted) is not None
        assert page.read_text(encoding="utf-8") == "nested page\n"
        assert (tmp_path / "memory/MEMORY.md").read_text(encoding="utf-8") == "fixed memory\n"
        assert (tmp_path / "memory/.dream_cursor").is_file()
        assert _git_output(tmp_path, "show", "HEAD:memory/wiki/deep/topic.md") == "nested page"

    def test_old_repository_and_snapshots_without_wiki_need_no_migration(self, tmp_path):
        old = GitStore(tmp_path, tracked_files=["SOUL.md"])
        old.init()
        (tmp_path / "SOUL.md").write_text("legacy state\n", encoding="utf-8")
        legacy = old.auto_commit("dream: before wiki")
        assert legacy is not None
        old_ignore = (tmp_path / ".gitignore").read_bytes()
        git = GitStore(tmp_path, tracked_files=["SOUL.md"], tracked_dirs=["memory/wiki"])
        assert git.init() is False
        page = _write_page(tmp_path, "memory/wiki/nested/new.md", "first wiki\n")
        created = git.auto_commit("dream: add wiki")
        assert created is not None
        assert _git_output(tmp_path, "show", "HEAD:memory/wiki/nested/new.md") == "first wiki"
        assert (tmp_path / ".gitignore").read_bytes() == old_ignore

        assert git.revert(created) is not None
        assert not page.exists()
        _write_page(tmp_path, "memory/wiki/later.md", "not in the old snapshot\n")
        assert git.auto_commit("dream: another wiki page") is not None
        assert git.revert(legacy) is not None
        assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == ""
        assert not list((tmp_path / "memory/wiki").rglob("*.md"))
        assert "memory/wiki" not in _git_output(tmp_path, "ls-tree", "-r", "--name-only", "HEAD")

    def test_empty_page_addition_and_deletion_are_not_lost_in_summary(self, wiki_git, tmp_path):
        page = _write_page(tmp_path, "memory/wiki/empty.md", "")
        assert "memory/wiki/empty.md: +0 -0" in wiki_git.summarize_working_tree(
            [], directories=["memory/wiki"],
        )
        assert wiki_git.auto_commit("dream: empty page") is not None
        page.unlink()
        assert "memory/wiki/empty.md: +0 -0" in wiki_git.summarize_working_tree(
            [], directories=["memory/wiki"],
        )
        assert wiki_git.auto_commit("dream: delete empty page") is not None


def _make_link(link, target, *, junction=False):
    if junction:
        if os.name != "nt":
            pytest.skip("junctions are Windows-only")
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, check=True,
        )
    else:
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")


class TestDirectoryBoundaries:

    @pytest.mark.parametrize(("kind", "location", "target_scope"), [
        ("symlink", "root", "history"),
        ("symlink", "nested", "outside"),
        ("symlink", "ancestor", "outside"),
        ("junction", "root", "history"),
        ("junction", "nested", "outside"),
        ("junction", "ancestor", "outside"),
    ])
    def test_directory_links_fail_before_staging_reading_or_restoring(
        self, tmp_path, kind, location, target_scope,
    ):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        git = GitStore(workspace, tracked_files=["SOUL.md"], tracked_dirs=["memory/wiki"])
        git.init()
        _write_page(workspace, "memory/wiki/page.md", "safe page\n")
        assert git.auto_commit("dream: safe page") is not None
        (workspace / "SOUL.md").write_text("latest soul\n", encoding="utf-8")
        latest = git.auto_commit("dream: latest")
        assert latest is not None

        target = workspace / "memory" if target_scope == "history" else tmp_path / "outside"
        target.mkdir(exist_ok=True)
        secret = _write_page(target, "history.jsonl", "synthetic private journal\n")
        link = {
            "root": workspace / "memory/wiki",
            "nested": workspace / "memory/wiki/escape",
            "ancestor": workspace / "memory",
        }[location]
        if link.exists():
            shutil.rmtree(link)
        _make_link(link, target, junction=kind == "junction")
        try:
            with pytest.raises(GitStoreError, match="auto-commit failed"):
                git.auto_commit("must not capture journal")
            with pytest.raises(GitStoreError, match="summary failed"):
                git.summarize_working_tree(["SOUL.md"], directories=["memory/wiki"])
            with pytest.raises(GitStoreError, match="revert failed"):
                git.revert(latest)
            assert git.log()[0].sha == latest
            assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "latest soul\n"
            assert secret.read_text(encoding="utf-8") == "synthetic private journal\n"
            assert _git_output(workspace, "diff", "--cached", "--exit-code") == ""
        finally:
            if kind == "junction":
                link.rmdir()
            else:
                link.unlink()

    @pytest.mark.parametrize("target_scope", ["history", "outside"])
    def test_page_symlink_does_not_read_or_overwrite_its_target(self, tmp_path, target_scope):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        git = GitStore(workspace, tracked_files=["SOUL.md"], tracked_dirs=["memory/wiki"])
        git.init()
        page = _write_page(workspace, "memory/wiki/page.md", "safe page\n")
        latest = git.auto_commit("dream: safe page")
        assert latest is not None
        if target_scope == "history":
            secret = _write_page(workspace, "memory/history.jsonl", "synthetic private journal\n")
        else:
            secret = _write_page(tmp_path, "outside/secret.md", "synthetic outside data\n")
        original = secret.read_bytes()
        page.unlink()
        _make_link(page, secret)
        try:
            with pytest.raises(GitStoreError, match="auto-commit failed"):
                git.auto_commit("must not capture link")
            with pytest.raises(GitStoreError, match="summary failed"):
                git.summarize_working_tree([], directories=["memory/wiki"])
            with pytest.raises(GitStoreError, match="summary failed"):
                git.summarize_working_tree(["memory/wiki/page.md"])
            with pytest.raises(GitStoreError, match="revert failed"):
                git.revert(latest)
            assert secret.read_bytes() == original
            assert git.log()[0].sha == latest
        finally:
            page.unlink()

    @pytest.mark.parametrize("kind", ["symlink", "junction"])
    def test_init_rejects_linked_ancestor_before_creating_fixed_files(self, tmp_path, kind):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "outside"
        sentinel = _write_page(outside, "wiki/private.md", "outside page\n")
        link = workspace / "memory"
        _make_link(link, outside, junction=kind == "junction")
        git = GitStore(
            workspace, tracked_files=["memory/MEMORY.md"], tracked_dirs=["memory/wiki"],
        )
        try:
            with pytest.raises(GitStoreError, match="init failed"):
                git.init()
            assert not (workspace / ".git").exists()
            assert not (outside / "MEMORY.md").exists()
            assert sentinel.read_text(encoding="utf-8") == "outside page\n"
        finally:
            if kind == "junction":
                link.rmdir()
            else:
                link.unlink()
