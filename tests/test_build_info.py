from __future__ import annotations

import subprocess
from pathlib import Path

from nanobot.build_info import read_commit


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def test_checkout_and_worktree_report_their_own_head(tmp_path: Path) -> None:
    git(tmp_path, "init")
    git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "--allow-empty", "-m", "initial")
    expected = git(tmp_path, "rev-parse", "HEAD")
    assert read_commit(tmp_path) == expected
    worktree = tmp_path / "checkout"
    git(tmp_path, "worktree", "add", "-b", "topic", str(worktree))
    git(worktree, "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "--allow-empty", "-m", "topic")
    assert read_commit(worktree) == git(worktree, "rev-parse", "HEAD")
    assert read_commit(worktree) != expected


def test_packaged_revision_ignores_an_enclosing_repository(tmp_path: Path) -> None:
    git(tmp_path, "init")
    git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "--allow-empty", "-m", "unrelated project")
    install_root = tmp_path / "site-packages"
    package = install_root / "nanobot"
    package.mkdir(parents=True)
    assert read_commit(install_root) is None
    stamp = package / "_build_commit.txt"
    stamp.write_text("a" * 40 + "\n", encoding="utf-8")
    assert read_commit(install_root) == "a" * 40
    stamp.write_text("unknown", encoding="utf-8")
    assert read_commit(install_root) is None
