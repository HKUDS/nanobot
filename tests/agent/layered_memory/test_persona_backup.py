"""Tests for USER.md backup rotation (LM3-B)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.layered_memory.persona.backup import (
    backup_user_md,
    list_backups,
    user_file_path,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def test_backup_user_md_creates_copy(workspace: Path) -> None:
    user_file_path(workspace).write_text("# User\n- dev\n", encoding="utf-8")
    dest = backup_user_md(workspace, keep=3)
    assert dest is not None
    assert dest.is_file()
    assert "dev" in dest.read_text(encoding="utf-8")


def test_backup_user_md_noop_when_missing(workspace: Path) -> None:
    assert backup_user_md(workspace, keep=3) is None


def test_backup_prunes_old_files(workspace: Path) -> None:
    user_file_path(workspace).write_text("v1", encoding="utf-8")
    backup_user_md(workspace, keep=2)
    user_file_path(workspace).write_text("v2", encoding="utf-8")
    backup_user_md(workspace, keep=2)
    user_file_path(workspace).write_text("v3", encoding="utf-8")
    backup_user_md(workspace, keep=2)
    assert len(list_backups(workspace)) <= 2
