"""Tests for AgentLoop._resolve_event_agent_workspace — event agent ACL routing."""

import json
from pathlib import Path

from nanobot.agent.loop import AgentLoop
from nanobot.agent.context import ContextBuilder
from nanobot.session.manager import SessionManager


def _mk_loop(workspace: Path) -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop.workspace = workspace
    loop._event_agent_cache = {}
    return loop


def _write_acl(workspace: Path, acl: dict) -> None:
    (workspace / "event_agent_acl.json").write_text(
        json.dumps(acl), encoding="utf-8"
    )


def _make_event_agent_workspace(workspace: Path, blocked_tools: list[str] | None = None) -> Path:
    ea_ws = workspace / "event_agent"
    ea_ws.mkdir(exist_ok=True)
    (ea_ws / "SOUL.md").write_text("# Event Agent\n")
    if blocked_tools is not None:
        (ea_ws / "blocked_tools.json").write_text(json.dumps(blocked_tools))
    return ea_ws


# ── No ACL file ───────────────────────────────────────────────────────────────

def test_returns_none_when_no_acl_file(tmp_path: Path) -> None:
    loop = _mk_loop(tmp_path)
    assert loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net") is None


# ── ACL file present but sender not in it ────────────────────────────────────

def test_returns_none_when_sender_not_in_acl(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"99999999999@s.whatsapp.net": {"name": "Other"}})
    loop = _mk_loop(tmp_path)
    assert loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net") is None


# ── Sender matched by full JID ────────────────────────────────────────────────

def test_matches_full_jid(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"}})
    _make_event_agent_workspace(tmp_path)
    loop = _mk_loop(tmp_path)
    result = loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net")
    assert result is not None
    ctx, sess, blocked = result
    assert isinstance(ctx, ContextBuilder)
    assert isinstance(sess, SessionManager)
    assert isinstance(blocked, frozenset)


# ── Sender matched by phone prefix (without @s.whatsapp.net) ─────────────────

def test_matches_phone_prefix(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"}})
    _make_event_agent_workspace(tmp_path)
    loop = _mk_loop(tmp_path)
    result = loop._resolve_event_agent_workspace("15551234567")
    assert result is not None


# ── event_agent workspace missing despite ACL match ──────────────────────────

def test_returns_none_when_workspace_dir_missing(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"}})
    # event_agent/ directory NOT created
    loop = _mk_loop(tmp_path)
    assert loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net") is None


# ── Corrupt ACL file ──────────────────────────────────────────────────────────

def test_returns_none_on_corrupt_acl(tmp_path: Path) -> None:
    (tmp_path / "event_agent_acl.json").write_text("not valid json", encoding="utf-8")
    loop = _mk_loop(tmp_path)
    assert loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net") is None


# ── Caching ───────────────────────────────────────────────────────────────────

def test_result_is_cached(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"}})
    _make_event_agent_workspace(tmp_path)
    loop = _mk_loop(tmp_path)
    result1 = loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net")
    result2 = loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net")
    assert result1 is result2  # same tuple object from cache


def test_cache_is_per_workspace_path(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"}})
    ea_ws = _make_event_agent_workspace(tmp_path)
    loop = _mk_loop(tmp_path)
    loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net")
    assert ea_ws in loop._event_agent_cache


# ── Multiple guests in ACL ────────────────────────────────────────────────────

def test_second_guest_also_matched(tmp_path: Path) -> None:
    _write_acl(tmp_path, {
        "15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"},
        "15559876543@s.whatsapp.net": {"name": "Mike", "event_id": "trip"},
    })
    _make_event_agent_workspace(tmp_path)
    loop = _mk_loop(tmp_path)
    assert loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net") is not None
    assert loop._resolve_event_agent_workspace("15559876543@s.whatsapp.net") is not None


def test_non_guest_not_matched_with_multiple_guests(tmp_path: Path) -> None:
    _write_acl(tmp_path, {
        "15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"},
        "15559876543@s.whatsapp.net": {"name": "Mike", "event_id": "trip"},
    })
    _make_event_agent_workspace(tmp_path)
    loop = _mk_loop(tmp_path)
    assert loop._resolve_event_agent_workspace("99999999999@s.whatsapp.net") is None


# ── blocked_tools loading ─────────────────────────────────────────────────────

def test_blocked_tools_loaded_from_workspace(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"}})
    _make_event_agent_workspace(tmp_path, blocked_tools=["write_file", "edit_file", "gmail_fetch"])
    loop = _mk_loop(tmp_path)
    _, _, blocked = loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net")
    assert blocked == frozenset({"write_file", "edit_file", "gmail_fetch"})


def test_blocked_tools_empty_when_no_file(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"}})
    _make_event_agent_workspace(tmp_path)  # no blocked_tools.json
    loop = _mk_loop(tmp_path)
    _, _, blocked = loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net")
    assert blocked == frozenset()


def test_blocked_tools_empty_on_corrupt_file(tmp_path: Path) -> None:
    _write_acl(tmp_path, {"15551234567@s.whatsapp.net": {"name": "Jake", "event_id": "trip"}})
    ea_ws = _make_event_agent_workspace(tmp_path)
    (ea_ws / "blocked_tools.json").write_text("not json")
    loop = _mk_loop(tmp_path)
    _, _, blocked = loop._resolve_event_agent_workspace("15551234567@s.whatsapp.net")
    assert blocked == frozenset()


# ── _load_blocked_tools ───────────────────────────────────────────────────────

def test_load_blocked_tools_reads_file(tmp_path: Path) -> None:
    (tmp_path / "blocked_tools.json").write_text(json.dumps(["read_file", "exec"]))
    result = AgentLoop._load_blocked_tools(tmp_path)
    assert result == frozenset({"read_file", "exec"})


def test_load_blocked_tools_missing_file(tmp_path: Path) -> None:
    assert AgentLoop._load_blocked_tools(tmp_path) == frozenset()
