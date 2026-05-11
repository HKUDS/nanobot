"""Slice C2 — MemoryStore + ContextBuilder honor per-user UserContext."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.auth.context import UserContext, current_user_ctx
from nanobot.auth.ids import new_ulid


@pytest.fixture()
def isolate_data_dir(monkeypatch, tmp_path: Path) -> Path:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    return tmp_path


@pytest.fixture()
def restore_ctx():
    token = current_user_ctx.set(None)
    yield
    current_user_ctx.reset(token)


def test_context_workspace_follows_user_context(
    isolate_data_dir: Path, restore_ctx
) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    ctx = UserContext(user_id=new_ulid())
    builder = ContextBuilder(global_ws)
    # Pre-ctx: workspace = global.
    assert builder.workspace == global_ws
    token = current_user_ctx.set(ctx)
    try:
        assert builder.workspace == ctx.workspace_path()
    finally:
        current_user_ctx.reset(token)
    assert builder.workspace == global_ws


def test_memorystore_per_user(isolate_data_dir: Path, restore_ctx) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    builder = ContextBuilder(global_ws)
    alice = UserContext(user_id=new_ulid())
    bob = UserContext(user_id=new_ulid())

    # Write a memory line as alice.
    token = current_user_ctx.set(alice)
    try:
        builder.memory.append_history("alice fact")
        alice_dir = builder.memory.memory_dir
        alice_history = builder.memory.history_file.read_text()
    finally:
        current_user_ctx.reset(token)

    # Write a memory line as bob.
    token = current_user_ctx.set(bob)
    try:
        builder.memory.append_history("bob fact")
        bob_dir = builder.memory.memory_dir
        bob_history = builder.memory.history_file.read_text()
    finally:
        current_user_ctx.reset(token)

    assert alice_dir != bob_dir
    # Both should be under per-user workspaces.
    assert str(alice.user_id) in str(alice_dir)
    assert str(bob.user_id) in str(bob_dir)
    # Bob's history should not contain alice's fact (and vice versa).
    assert "alice fact" not in bob_history
    assert "alice fact" in alice_history
    assert "bob fact" in bob_history
    assert "bob fact" not in alice_history


def test_memorystore_unset_ctx_returns_default(
    isolate_data_dir: Path, restore_ctx
) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    builder = ContextBuilder(global_ws)
    default = builder.memory
    # Repeated access without ctx returns the same singleton (cached default).
    assert builder.memory is default
    assert default.memory_dir == global_ws / "memory"


def test_memorystore_is_cached_per_user(
    isolate_data_dir: Path, restore_ctx
) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    builder = ContextBuilder(global_ws)
    ctx = UserContext(user_id=new_ulid())
    token = current_user_ctx.set(ctx)
    try:
        first = builder.memory
        second = builder.memory
    finally:
        current_user_ctx.reset(token)
    assert first is second


def test_skills_loader_per_user(isolate_data_dir: Path, restore_ctx) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    builder = ContextBuilder(global_ws)
    ctx = UserContext(user_id=new_ulid())
    default = builder.skills
    token = current_user_ctx.set(ctx)
    try:
        user_loader = builder.skills
    finally:
        current_user_ctx.reset(token)
    assert default is not user_loader
