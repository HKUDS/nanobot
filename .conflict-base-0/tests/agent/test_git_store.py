"""Tests for GitStore — git-backed version control for memory files."""

import pytest
from pathlib import Path

from nanobot.utils.gitstore import GitStore, CommitInfo


TRACKED = ["SOUL.md", "USER.md", "memory/MEMORY.md"]


@pytest.fixture
def git(tmp_path):
    """Uninitialized GitStore."""
    return GitStore(tmp_path, tracked_files=TRACKED)


@pytest.fixture
def git_ready(git):
    """Initialized GitStore with one initial commit."""
    git.init()
    return git


class TestInit:
    def test_not_initialized_by_default(self, git, tmp_path):
        assert not git.is_initialized()
        assert not (tmp_path / ".git").is_dir()

    def test_init_creates_git_dir(self, git, tmp_path):
        assert git.init()
        assert (tmp_path / ".git").is_dir()

    def test_init_idempotent(self, git_ready):
        assert not git_ready.init()

    def test_init_creates_gitignore(self, git_ready):
        gi = git_ready._workspace / ".gitignore"
        assert gi.exists()
        content = gi.read_text(encoding="utf-8")
        for f in TRACKED:
            assert f"!{f}" in content

    def test_init_touches_tracked_files(self, git_ready):
        for f in TRACKED:
            assert (git_ready._workspace / f).exists()

    def test_init_makes_initial_commit(self, git_ready):
        commits = git_ready.log()
        assert len(commits) == 1
        assert "init" in commits[0].message


class TestBuildGitignore:
    def test_subdirectory_dirs(self, git):
        content = git._build_gitignore()
        assert "!memory/\n" in content
        for f in TRACKED:
            assert f"!{f}\n" in content
        assert content.startswith("/*\n")

    def test_root_level_files_no_dir_entries(self, tmp_path):
        gs = GitStore(tmp_path, tracked_files=["a.md", "b.md"])
        content = gs._build_gitignore()
        assert "!a.md\n" in content
        assert "!b.md\n" in content
        dir_lines = [l for l in content.split("\n") if l.startswith("!") and l.endswith("/")]
        assert dir_lines == []


class TestAutoCommit:
    def test_returns_none_when_not_initialized(self, git):
        assert git.auto_commit("test") is None

    def test_commits_file_change(self, git_ready):
        (git_ready._workspace / "SOUL.md").write_text("updated", encoding="utf-8")
        sha = git_ready.auto_commit("update soul")
        assert sha is not None
        assert len(sha) == 8

    def test_returns_none_when_no_changes(self, git_ready):
        assert git_ready.auto_commit("no change") is None

    def test_commit_appears_in_log(self, git_ready):
        ws = git_ready._workspace
        (ws / "SOUL.md").write_text("v2", encoding="utf-8")
        sha = git_ready.auto_commit("update soul")
        commits = git_ready.log()
        assert len(commits) == 2
        assert commits[0].sha == sha

    def test_does_not_create_empty_commits(self, git_ready):
        git_ready.auto_commit("nothing 1")
        git_ready.auto_commit("nothing 2")
        assert len(git_ready.log()) == 1  # only init commit


class TestLog:
    def test_empty_when_not_initialized(self, git):
        assert git.log() == []

    def test_newest_first(self, git_ready):
        ws = git_ready._workspace
        for i in range(3):
            (ws / "SOUL.md").write_text(f"v{i}", encoding="utf-8")
            git_ready.auto_commit(f"commit {i}")

        commits = git_ready.log()
        assert len(commits) == 4  # init + 3
        assert "commit 2" in commits[0].message
        assert "init" in commits[-1].message

    def test_max_entries(self, git_ready):
        ws = git_ready._workspace
        for i in range(10):
            (ws / "SOUL.md").write_text(f"v{i}", encoding="utf-8")
            git_ready.auto_commit(f"c{i}")
        assert len(git_ready.log(max_entries=3)) == 3

    def test_commit_info_fields(self, git_ready):
        c = git_ready.log()[0]
        assert isinstance(c, CommitInfo)
        assert len(c.sha) == 8
        assert c.timestamp
        assert c.message


class TestDiffCommits:
    def test_empty_when_not_initialized(self, git):
        assert git.diff_commits("a", "b") == ""

    def test_diff_between_two_commits(self, git_ready):
        ws = git_ready._workspace
        (ws / "SOUL.md").write_text("original", encoding="utf-8")
        git_ready.auto_commit("v1")
        (ws / "SOUL.md").write_text("modified", encoding="utf-8")
        git_ready.auto_commit("v2")

        commits = git_ready.log()
        diff = git_ready.diff_commits(commits[1].sha, commits[0].sha)
        assert "modified" in diff

    def test_invalid_sha_returns_empty(self, git_ready):
        assert git_ready.diff_commits("deadbeef", "cafebabe") == ""


class TestFindCommit:
    def test_finds_by_prefix(self, git_ready):
        ws = git_ready._workspace
        (ws / "SOUL.md").write_text("v2", encoding="utf-8")
        sha = git_ready.auto_commit("v2")
        found = git_ready.find_commit(sha[:4])
        assert found is not None
        assert found.sha == sha

    def test_returns_none_for_unknown(self, git_ready):
        assert git_ready.find_commit("deadbeef") is None


class TestShowCommitDiff:
    def test_returns_commit_with_diff(self, git_ready):
        ws = git_ready._workspace
        (ws / "SOUL.md").write_text("content", encoding="utf-8")
        sha = git_ready.auto_commit("add content")
        result = git_ready.show_commit_diff(sha)
        assert result is not None
        commit, diff = result
        assert commit.sha == sha
        assert "content" in diff

    def test_first_commit_has_empty_diff(self, git_ready):
        init_sha = git_ready.log()[-1].sha
        result = git_ready.show_commit_diff(init_sha)
        assert result is not None
        _, diff = result
        assert diff == ""

    def test_returns_none_for_unknown(self, git_ready):
        assert git_ready.show_commit_diff("deadbeef") is None


class TestCommitInfoFormat:
    def test_format_with_diff(self):
        from nanobot.utils.gitstore import CommitInfo
        c = CommitInfo(sha="abcd1234", message="test commit\nsecond line", timestamp="2026-04-02 12:00")
        result = c.format(diff="some diff")
        assert "test commit" in result
        assert "`abcd1234`" in result
        assert "some diff" in result

    def test_format_without_diff(self):
        from nanobot.utils.gitstore import CommitInfo
        c = CommitInfo(sha="abcd1234", message="test", timestamp="2026-04-02 12:00")
        result = c.format()
        assert "(no file changes)" in result


class TestRevert:
    def test_returns_none_when_not_initialized(self, git):
        assert git.revert("abc") is None

    def test_undoes_commit_changes(self, git_ready):
        """revert(sha) should undo the given commit by restoring to its parent."""
        ws = git_ready._workspace
        (ws / "SOUL.md").write_text("v2 content", encoding="utf-8")
        git_ready.auto_commit("v2")

        commits = git_ready.log()
        # commits[0] = v2 (HEAD), commits[1] = init
        # Revert v2 → restore to init's state (empty SOUL.md)
        new_sha = git_ready.revert(commits[0].sha)
        assert new_sha is not None
        assert (ws / "SOUL.md").read_text(encoding="utf-8") == ""

    def test_root_commit_returns_none(self, git_ready):
        """Cannot revert the root commit (no parent to restore to)."""
        commits = git_ready.log()
        assert len(commits) == 1
        assert git_ready.revert(commits[0].sha) is None

    def test_invalid_sha_returns_none(self, git_ready):
        assert git_ready.revert("deadbeef") is None


class TestMemoryStoreGitProperty:
    def test_git_property_exposes_gitstore(self, tmp_path):
        from nanobot.agent.memory import MemoryStore
        store = MemoryStore(tmp_path)
        assert isinstance(store.git, GitStore)

    def test_git_property_is_same_object(self, tmp_path):
        from nanobot.agent.memory import MemoryStore
        store = MemoryStore(tmp_path)
        assert store.git is store._git
