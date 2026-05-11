"""Slice C1 — filesystem & shell tools honor per-user UserContext."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nanobot.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)
from nanobot.agent.tools.shell import ExecTool
from nanobot.auth.context import UserContext, current_user_ctx
from nanobot.auth.ids import new_ulid


@pytest.fixture()
def isolate_data_dir(monkeypatch, tmp_path: Path) -> Path:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    return tmp_path


@pytest.fixture()
def restore_ctx():
    """Always restore the contextvar after a test."""
    token = current_user_ctx.set(None)
    yield
    current_user_ctx.reset(token)


def _make_fs_tools(workspace: Path):
    return {
        "write": WriteFileTool(workspace=workspace, allowed_dir=workspace),
        "read": ReadFileTool(workspace=workspace, allowed_dir=workspace),
        "edit": EditFileTool(workspace=workspace, allowed_dir=workspace),
        "ls": ListDirTool(workspace=workspace, allowed_dir=workspace),
    }


def test_filesystem_tool_writes_under_user_workspace(
    isolate_data_dir: Path, restore_ctx
) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    tools = _make_fs_tools(global_ws)
    uid = new_ulid()
    ctx = UserContext(user_id=uid)
    token = current_user_ctx.set(ctx)
    try:
        asyncio.run(tools["write"].execute(path="notes.md", content="user-scoped file"))
    finally:
        current_user_ctx.reset(token)

    expected = isolate_data_dir / "users" / uid / "workspace" / "notes.md"
    assert expected.is_file()
    assert expected.read_text() == "user-scoped file"
    # The legacy workspace must stay untouched.
    assert not (global_ws / "notes.md").exists()


def test_filesystem_tool_writes_to_global_when_ctx_unset(
    isolate_data_dir: Path, restore_ctx
) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    tools = _make_fs_tools(global_ws)
    # current_user_ctx is None by virtue of the fixture; CLI / channel path.
    asyncio.run(tools["write"].execute(path="cli.md", content="from cli"))
    assert (global_ws / "cli.md").is_file()


def test_filesystem_tools_for_two_users_disjoint(
    isolate_data_dir: Path, restore_ctx
) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    tools = _make_fs_tools(global_ws)
    alice = UserContext(user_id=new_ulid())
    bob = UserContext(user_id=new_ulid())

    token = current_user_ctx.set(alice)
    try:
        asyncio.run(tools["write"].execute(path="secret.txt", content="alice-secret"))
    finally:
        current_user_ctx.reset(token)

    # Bob's list should NOT see alice's file.
    token = current_user_ctx.set(bob)
    try:
        listing = asyncio.run(tools["ls"].execute(path="."))
    finally:
        current_user_ctx.reset(token)

    assert "secret.txt" not in str(listing)

    alice_path = isolate_data_dir / "users" / alice.user_id / "workspace" / "secret.txt"
    bob_path = isolate_data_dir / "users" / bob.user_id / "workspace" / "secret.txt"
    assert alice_path.is_file()
    assert not bob_path.exists()


def test_filesystem_tool_read_back_within_user_context(
    isolate_data_dir: Path, restore_ctx
) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    tools = _make_fs_tools(global_ws)
    ctx = UserContext(user_id=new_ulid())
    token = current_user_ctx.set(ctx)
    try:
        asyncio.run(tools["write"].execute(path="round.txt", content="hello round trip"))
        result = asyncio.run(tools["read"].execute(path="round.txt"))
    finally:
        current_user_ctx.reset(token)
    assert "hello round trip" in str(result)


def test_exec_tool_working_dir_follows_user_context(
    isolate_data_dir: Path, restore_ctx
) -> None:
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    tool = ExecTool(working_dir=str(global_ws), restrict_to_workspace=True)
    ctx = UserContext(user_id=new_ulid())
    user_ws = isolate_data_dir / "users" / ctx.user_id / "workspace"

    assert tool.working_dir == str(global_ws)
    token = current_user_ctx.set(ctx)
    try:
        assert tool.working_dir == str(user_ws)
    finally:
        current_user_ctx.reset(token)
    # Reverts on reset.
    assert tool.working_dir == str(global_ws)


def test_filesystem_tool_blocks_escape_outside_user_workspace(
    isolate_data_dir: Path, restore_ctx, tmp_path: Path
) -> None:
    """When the loop restricted writes to the workspace, that restriction
    must rebind to the user's workspace under a UserContext — not stay on
    the global workspace."""
    global_ws = isolate_data_dir / "workspace"
    global_ws.mkdir()
    tools = _make_fs_tools(global_ws)
    ctx = UserContext(user_id=new_ulid())
    other = tmp_path / "outside"
    other.mkdir()

    token = current_user_ctx.set(ctx)
    try:
        result = asyncio.run(
            tools["write"].execute(path=str(other / "leak.txt"), content="x")
        )
    finally:
        current_user_ctx.reset(token)
    assert "outside allowed directory" in str(result).lower() or "permission" in str(result).lower()
