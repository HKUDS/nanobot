"""Slice A5 integration: per-user SessionManager + AgentLoop routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.auth import UserContext
from nanobot.auth.ids import new_ulid
from nanobot.config.paths import get_user_root, get_users_root
from nanobot.session.manager import SessionManager


@pytest.fixture()
def isolate_data_dir(monkeypatch, tmp_path: Path):
    """Redirect nanobot.config.paths.get_data_dir to a temp directory."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)
    return tmp_path


def test_session_manager_with_user_ctx_writes_under_user_dir(isolate_data_dir: Path) -> None:
    """SessionManager with user_ctx must persist sessions under users/<uid>/sessions/."""
    workspace = isolate_data_dir / "workspace"
    workspace.mkdir()
    uid = new_ulid()
    ctx = UserContext(user_id=uid)
    sm = SessionManager(workspace, user_ctx=ctx)

    session = sm.get_or_create("websocket:web-1")
    session.add_message("user", "hello")
    sm.save(session)

    user_path = get_user_root(uid) / "sessions" / "websocket_web-1.jsonl"
    legacy_path = workspace / "sessions" / "websocket_web-1.jsonl"
    assert user_path.exists(), f"session file should land under {user_path}"
    assert not legacy_path.exists(), f"session file leaked to legacy path {legacy_path}"


def test_two_users_have_disjoint_session_files(isolate_data_dir: Path) -> None:
    workspace = isolate_data_dir / "workspace"
    workspace.mkdir()
    alice = UserContext(user_id=new_ulid())
    bob = UserContext(user_id=new_ulid())
    sm_a = SessionManager(workspace, user_ctx=alice)
    sm_b = SessionManager(workspace, user_ctx=bob)

    sa = sm_a.get_or_create("websocket:shared-key")
    sa.add_message("user", "alice message")
    sm_a.save(sa)

    sb = sm_b.get_or_create("websocket:shared-key")
    sb.add_message("user", "bob message")
    sm_b.save(sb)

    a_path = get_user_root(alice.user_id) / "sessions" / "websocket_shared-key.jsonl"
    b_path = get_user_root(bob.user_id) / "sessions" / "websocket_shared-key.jsonl"
    assert a_path.exists()
    assert b_path.exists()
    assert a_path != b_path
    assert "alice" in a_path.read_text()
    assert "bob" in b_path.read_text()
    assert "alice" not in b_path.read_text()
    assert "bob" not in a_path.read_text()


def test_global_session_manager_unchanged(isolate_data_dir: Path) -> None:
    """SessionManager without user_ctx keeps legacy workspace/sessions/ layout."""
    workspace = isolate_data_dir / "workspace"
    workspace.mkdir()
    sm = SessionManager(workspace)

    session = sm.get_or_create("cli:default")
    session.add_message("user", "cli message")
    sm.save(session)

    assert (workspace / "sessions" / "cli_default.jsonl").exists()
    # Crucially, nothing landed under users/ for this path.
    if get_users_root().exists():
        assert not list(get_users_root().rglob("cli_default.jsonl"))


def test_agent_loop_sessions_for_routing(isolate_data_dir: Path) -> None:
    """AgentLoop._sessions_for returns global for None ctx and a per-user
    SessionManager for a UserContext (cached across calls)."""
    from nanobot.agent.loop import AgentLoop  # local import: heavy module

    workspace = isolate_data_dir / "workspace"
    workspace.mkdir()
    loop = AgentLoop.__new__(AgentLoop)
    # Wire only the attributes _sessions_for depends on, to avoid full ctor cost.
    loop.workspace = workspace
    loop.sessions = SessionManager(workspace)
    loop._user_session_managers = {}

    assert loop._sessions_for(None) is loop.sessions

    ctx = UserContext(user_id=new_ulid())
    sm1 = loop._sessions_for(ctx)
    sm2 = loop._sessions_for(ctx)
    assert sm1 is sm2  # cached
    assert sm1 is not loop.sessions
    assert sm1.sessions_dir == ctx.sessions_dir()
