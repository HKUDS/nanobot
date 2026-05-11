"""Tests for nanobot.auth.context.UserContext."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.auth.context import UserContext
from nanobot.auth.ids import new_ulid


@pytest.fixture()
def ctx(monkeypatch, tmp_path: Path) -> UserContext:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    return UserContext(user_id=new_ulid())


def test_invalid_user_id_rejected() -> None:
    with pytest.raises(ValueError):
        UserContext(user_id="not-a-ulid")
    with pytest.raises(ValueError):
        UserContext(user_id="")


def test_root_under_users_dir(ctx: UserContext, tmp_path: Path) -> None:
    assert ctx.root() == tmp_path / "users" / ctx.user_id
    assert ctx.root().is_dir()


def test_subdirs_resolve_under_root(ctx: UserContext) -> None:
    root = ctx.root()
    assert ctx.workspace_path() == root / "workspace"
    assert ctx.sessions_dir() == root / "sessions"
    assert ctx.memory_dir() == root / "memory"
    assert ctx.media_dir() == root / "media"
    assert ctx.media_dir("telegram") == root / "media" / "telegram"
    assert ctx.tool_results_dir() == root / "tool-results"
    assert ctx.file_state_dir() == root / "file_state"
    assert ctx.profile_path() == root / "profile.json"


def test_directories_are_created(ctx: UserContext) -> None:
    assert ctx.workspace_path().is_dir()
    assert ctx.sessions_dir().is_dir()
    assert ctx.memory_dir().is_dir()
    assert ctx.media_dir("slack").is_dir()
    assert ctx.tool_results_dir().is_dir()
    assert ctx.file_state_dir().is_dir()


def test_two_contexts_isolated(monkeypatch, tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    a = UserContext(user_id=new_ulid())
    b = UserContext(user_id=new_ulid())
    assert a.root() != b.root()
    assert a.workspace_path() != b.workspace_path()


def test_context_is_hashable_and_frozen() -> None:
    uid = new_ulid()
    ctx = UserContext(user_id=uid)
    # Hashable
    assert {ctx} == {UserContext(user_id=uid)}
    # Frozen
    with pytest.raises(Exception):
        ctx.user_id = new_ulid()  # type: ignore[misc]
