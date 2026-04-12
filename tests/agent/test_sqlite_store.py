"""Tests for SQLiteStore — SQLite-backed version control for memory files."""

import pytest
from pathlib import Path

from nanobot.utils.sqlitestore import SQLiteStore
from nanobot.utils.version_store import CommitInfo


TRACKED = ["SOUL.md", "USER.md", "memory/MEMORY.md"]


@pytest.fixture
def store(tmp_path):
    """Uninitialized SQLiteStore."""
    return SQLiteStore(tmp_path, tracked_files=TRACKED)


@pytest.fixture
def store_ready(store):
    """Initialized SQLiteStore."""
    store.init()
    return store


class TestInit:
    def test_not_initialized_by_default(self, store, tmp_path):
        assert not store.is_initialized()
        assert not (tmp_path / "memory" / ".dream_history.db").exists()

    def test_init_creates_db(self, store, tmp_path):
        assert store.init()
        assert (tmp_path / "memory" / ".dream_history.db").exists()

    def test_init_idempotent(self, store_ready):
        assert not store_ready.init()

    def test_init_touches_tracked_files(self, store_ready):
        for f in TRACKED:
            assert (store_ready._workspace / f).exists()


class TestAutoCommit:
    def test_auto_init_on_first_commit(self, store):
        """auto_commit should auto-initialize if not already initialized."""
        (store._workspace / "SOUL.md").parent.mkdir(parents=True, exist_ok=True)
        (store._workspace / "SOUL.md").write_text("test", encoding="utf-8")
        sha = store.auto_commit("first commit")
        assert sha is not None
        assert store.is_initialized()

    def test_commits_file_change(self, store_ready):
        (store_ready._workspace / "SOUL.md").write_text("updated", encoding="utf-8")
        sha = store_ready.auto_commit("update soul")
        assert sha is not None
        assert len(sha) == 8

    def test_returns_none_when_no_changes(self, store_ready):
        # First commit records the current state
        sha1 = store_ready.auto_commit("first")
        assert sha1 is not None
        # Second commit with no changes returns None
        assert store_ready.auto_commit("no change") is None

    def test_commit_appears_in_log(self, store_ready):
        ws = store_ready._workspace
        (ws / "SOUL.md").write_text("v2", encoding="utf-8")
        sha = store_ready.auto_commit("update soul")
        commits = store_ready.log()
        assert len(commits) == 1
        assert commits[0].sha == sha

    def test_does_not_create_empty_commits(self, store_ready):
        # First commit records current state
        sha1 = store_ready.auto_commit("first")
        assert sha1 is not None
        # Second commit with no changes should not create a new commit
        sha2 = store_ready.auto_commit("nothing 2")
        assert sha2 is None
        assert len(store_ready.log()) == 1


class TestLog:
    def test_empty_when_not_initialized(self, store):
        assert store.log() == []

    def test_newest_first(self, store_ready):
        ws = store_ready._workspace
        for i in range(3):
            (ws / "SOUL.md").write_text(f"v{i}", encoding="utf-8")
            store_ready.auto_commit(f"commit {i}")

        commits = store_ready.log()
        assert len(commits) == 3
        assert "commit 2" in commits[0].message
        assert "commit 0" in commits[-1].message

    def test_max_entries(self, store_ready):
        ws = store_ready._workspace
        for i in range(10):
            (ws / "SOUL.md").write_text(f"v{i}", encoding="utf-8")
            store_ready.auto_commit(f"c{i}")
        assert len(store_ready.log(max_entries=3)) == 3

    def test_commit_info_fields(self, store_ready):
        (store_ready._workspace / "SOUL.md").write_text("v2", encoding="utf-8")
        store_ready.auto_commit("test")
        c = store_ready.log()[0]
        assert isinstance(c, CommitInfo)
        assert len(c.sha) == 8
        assert c.timestamp
        assert c.message


class TestFindCommit:
    def test_finds_by_prefix(self, store_ready):
        ws = store_ready._workspace
        (ws / "SOUL.md").write_text("v2", encoding="utf-8")
        sha = store_ready.auto_commit("v2")
        found = store_ready.find_commit(sha[:4])
        assert found is not None
        assert found.sha == sha

    def test_returns_none_for_unknown(self, store_ready):
        assert store_ready.find_commit("deadbeef") is None


class TestShowCommitDiff:
    def test_returns_commit_with_diff(self, store_ready):
        ws = store_ready._workspace
        (ws / "SOUL.md").write_text("content", encoding="utf-8")
        sha = store_ready.auto_commit("add content")
        result = store_ready.show_commit_diff(sha)
        assert result is not None
        commit, diff = result
        assert commit.sha == sha
        assert "content" in diff

    def test_first_commit_has_diff_from_empty(self, store_ready):
        """First commit shows diff from empty state."""
        ws = store_ready._workspace
        (ws / "SOUL.md").write_text("initial", encoding="utf-8")
        sha = store_ready.auto_commit("initial")
        result = store_ready.show_commit_diff(sha)
        assert result is not None
        _, diff = result
        assert "initial" in diff

    def test_returns_none_for_unknown(self, store_ready):
        assert store_ready.show_commit_diff("deadbeef") is None

    def test_diff_shows_removal(self, store_ready):
        """Diff should show removed content when reverting."""
        ws = store_ready._workspace
        (ws / "SOUL.md").write_text("original", encoding="utf-8")
        sha1 = store_ready.auto_commit("v1")
        (ws / "SOUL.md").write_text("modified", encoding="utf-8")
        sha2 = store_ready.auto_commit("v2")
        result = store_ready.show_commit_diff(sha2)
        assert result is not None
        _, diff = result
        assert "modified" in diff
        assert "-original" in diff or "original" in diff


class TestCommitInfoFormat:
    def test_format_with_diff(self):
        c = CommitInfo(sha="abcd1234", message="test commit\nsecond line", timestamp="2026-04-02 12:00")
        result = c.format(diff="some diff")
        assert "test commit" in result
        assert "`abcd1234`" in result
        assert "some diff" in result

    def test_format_without_diff(self):
        c = CommitInfo(sha="abcd1234", message="test", timestamp="2026-04-02 12:00")
        result = c.format()
        assert "(no file changes)" in result


class TestRevert:
    def test_returns_none_when_not_initialized(self, store):
        assert store.revert("abc") is None

    def test_undoes_commit_changes(self, store_ready):
        """revert(sha) should undo the given commit by restoring to its parent."""
        ws = store_ready._workspace
        (ws / "SOUL.md").write_text("v1 content", encoding="utf-8")
        store_ready.auto_commit("v1")
        (ws / "SOUL.md").write_text("v2 content", encoding="utf-8")
        store_ready.auto_commit("v2")

        commits = store_ready.log()
        # commits[0] = v2 (HEAD), commits[1] = v1
        # Revert v2 → restore to v1's state
        new_sha = store_ready.revert(commits[0].sha)
        assert new_sha is not None
        assert (ws / "SOUL.md").read_text(encoding="utf-8") == "v1 content"

    def test_oldest_commit_returns_none(self, store_ready):
        """Cannot revert the oldest commit (no parent to restore to)."""
        ws = store_ready._workspace
        (ws / "SOUL.md").write_text("first", encoding="utf-8")
        store_ready.auto_commit("first")
        commits = store_ready.log()
        assert len(commits) == 1
        assert store_ready.revert(commits[0].sha) is None

    def test_invalid_sha_returns_none(self, store_ready):
        assert store_ready.revert("deadbeef") is None


class TestMemoryStoreSQLiteProperty:
    def test_version_store_is_sqlite_by_default(self, tmp_path):
        from nanobot.agent.memory import MemoryStore
        store = MemoryStore(tmp_path, version_backend="sqlite")
        assert isinstance(store.git, SQLiteStore)

    def test_version_store_is_git_when_configured(self, tmp_path):
        from nanobot.agent.memory import MemoryStore
        from nanobot.utils.gitstore import GitStore
        store = MemoryStore(tmp_path, version_backend="git")
        assert isinstance(store.git, GitStore)

    def test_version_store_is_same_object(self, tmp_path):
        from nanobot.agent.memory import MemoryStore
        store = MemoryStore(tmp_path, version_backend="sqlite")
        assert store.git is store._version_store
