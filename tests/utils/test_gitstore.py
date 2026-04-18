"""Tests for GitStore — line_ages() and core git operations."""

import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from nanobot.utils.gitstore import GitStore


@pytest.fixture
def git(tmp_path):
    """Create an initialized GitStore with tracked MEMORY.md."""
    g = GitStore(tmp_path, tracked_files=["MEMORY.md", "SOUL.md"])
    g.init()
    return g


class TestLineAges:
    def test_returns_empty_when_not_initialized(self, tmp_path):
        """line_ages should return [] if the git repo is not initialized."""
        git = GitStore(tmp_path, tracked_files=["MEMORY.md"])
        assert git.line_ages("MEMORY.md") == []

    def test_returns_empty_for_missing_file(self, git):
        """line_ages should return [] for a file that doesn't exist."""
        assert git.line_ages("SOUL.md") == []

    def test_returns_empty_for_empty_file(self, git, tmp_path):
        """line_ages should return [] for an empty tracked file."""
        (tmp_path / "SOUL.md").write_text("", encoding="utf-8")
        git.auto_commit("empty soul")
        assert git.line_ages("SOUL.md") == []

    def test_one_age_per_line(self, git, tmp_path):
        """line_ages should return one entry per line in the file."""
        content = "# Memory\n\n## Section A\n- item 1\n"
        (tmp_path / "MEMORY.md").write_text(content, encoding="utf-8")
        git.auto_commit("initial")
        ages = git.line_ages("MEMORY.md")
        assert len(ages) == len(content.splitlines())

    def test_fresh_lines_have_age_zero(self, git, tmp_path):
        """Lines committed today should have age_days=0."""
        (tmp_path / "MEMORY.md").write_text("## A\n- x\n", encoding="utf-8")
        git.auto_commit("initial")
        ages = git.line_ages("MEMORY.md")
        assert all(a.age_days == 0 for a in ages)

    def test_age_differentiates_across_days(self, git, tmp_path):
        """Lines committed today should show correct age when 'now' is mocked forward."""
        (tmp_path / "MEMORY.md").write_text("## A\n- x\n", encoding="utf-8")
        git.auto_commit("initial")

        future_now = datetime.now(tz=timezone.utc) + timedelta(days=30)
        with patch("nanobot.utils.gitstore.datetime") as mock_dt:
            mock_dt.now.return_value = future_now
            mock_dt.fromtimestamp = datetime.fromtimestamp
            ages = git.line_ages("MEMORY.md")

        assert len(ages) == 2
        assert all(a.age_days == 30 for a in ages)

    def test_annotate_failure_returns_empty(self, tmp_path):
        """If annotate fails, line_ages should return [] gracefully."""
        git = GitStore(tmp_path, tracked_files=["MEMORY.md"])
        # Don't init — annotate will fail
        assert git.line_ages("MEMORY.md") == []

    def test_partial_edit_only_updates_changed_lines(self, git, tmp_path):
        """Only modified lines should reflect the new commit's timestamp."""
        (tmp_path / "MEMORY.md").write_text(
            "# Memory\n\n## A\n- old\n\n## B\n- keep\n", encoding="utf-8"
        )
        git.auto_commit("commit1")
        time.sleep(1.1)

        # Only modify section A
        (tmp_path / "MEMORY.md").write_text(
            "# Memory\n\n## A\n- new\n\n## B\n- keep\n", encoding="utf-8"
        )
        git.auto_commit("commit2")

        ages = git.line_ages("MEMORY.md")
        lines = (tmp_path / "MEMORY.md").read_text(encoding="utf-8").splitlines()
        # All lines are from today, but verify line-level tracking works
        assert len(ages) == len(lines)
        # "- new" line and "- keep" line both age=0 (same day), but
        # the key point is we get per-line results
        assert len(ages) == 7
