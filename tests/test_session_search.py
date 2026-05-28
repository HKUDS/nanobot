"""Tests for SessionSearchTool — cross-session memory query.

Addresses the failure observed 2026-05-28 20:40: Iroh-in-Steve's-session
couldn't surface what Iroh-in-Glyn's-session had just learned, because the
two sessions don't share working memory and consolidation hadn't fired.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nanobot.agent.tools.sessions import SessionSearchTool


def _write_session(workspace: Path, key: str, messages: list[dict]) -> Path:
    """Write a jsonl session file mirroring nanobot's on-disk format."""
    sessions_dir = workspace / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    path = sessions_dir / f"{key}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for m in messages:
            f.write(json.dumps(m) + "\n")
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def now_iso() -> str:
    return datetime.now().isoformat()


# ---- basic matching ----------------------------------------------------------


@pytest.mark.asyncio
async def test_finds_match_across_sessions(workspace: Path, now_iso: str) -> None:
    _write_session(workspace, "telegram_8341580836", [
        {"role": "user", "content": "I'm feeling really low today", "timestamp": now_iso},
        {"role": "assistant", "content": "I'm sorry to hear that, Glyn — tell me more", "timestamp": now_iso},
    ])
    _write_session(workspace, "telegram_8775031757", [
        {"role": "user", "content": "Any updates from your side?", "timestamp": now_iso},
    ])

    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="feeling really low")

    assert "telegram_8341580836" in out
    assert "feeling really low" in out
    assert "telegram_8775031757" not in out


@pytest.mark.asyncio
async def test_case_insensitive(workspace: Path, now_iso: str) -> None:
    _write_session(workspace, "t_x", [
        {"role": "user", "content": "Flight booking U22461", "timestamp": now_iso},
    ])
    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="u22461")
    assert "U22461" in out


@pytest.mark.asyncio
async def test_no_match_reports_clearly(workspace: Path, now_iso: str) -> None:
    _write_session(workspace, "t_x", [
        {"role": "user", "content": "nothing relevant", "timestamp": now_iso},
    ])
    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="unicorn")
    assert "No matches" in out


@pytest.mark.asyncio
async def test_no_sessions_dir(workspace: Path) -> None:
    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="x")
    assert "No sessions directory" in out


# ---- time window -------------------------------------------------------------


@pytest.mark.asyncio
async def test_filters_by_days(workspace: Path) -> None:
    now = datetime.now()
    old = (now - timedelta(days=60)).isoformat()
    recent = now.isoformat()
    _write_session(workspace, "t_x", [
        {"role": "user", "content": "ancient mood dip", "timestamp": old},
        {"role": "user", "content": "recent mood dip", "timestamp": recent},
    ])
    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="mood dip", days=30)
    assert "recent mood dip" in out
    assert "ancient mood dip" not in out


# ---- session filter ----------------------------------------------------------


@pytest.mark.asyncio
async def test_session_filter_restricts(workspace: Path, now_iso: str) -> None:
    _write_session(workspace, "telegram_glyn", [
        {"role": "user", "content": "hi", "timestamp": now_iso},
    ])
    _write_session(workspace, "telegram_steve", [
        {"role": "user", "content": "hi", "timestamp": now_iso},
    ])
    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="hi", session="telegram_glyn")
    assert "telegram_glyn" in out
    assert "telegram_steve" not in out


@pytest.mark.asyncio
async def test_session_filter_unknown(workspace: Path, now_iso: str) -> None:
    _write_session(workspace, "telegram_glyn", [
        {"role": "user", "content": "hi", "timestamp": now_iso},
    ])
    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="hi", session="nope")
    assert "No session matching" in out


# ---- tool calls and structured content ---------------------------------------


@pytest.mark.asyncio
async def test_matches_inside_tool_call_arguments(workspace: Path, now_iso: str) -> None:
    """A real Iroh failure: it called the message tool to flag Glyn's mood dip
    to Steve. The text 'mood dip' lives inside tool_calls[0].function.arguments,
    not in content. Search must reach it."""
    _write_session(workspace, "telegram_glyn", [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "x",
                "type": "function",
                "function": {
                    "name": "message",
                    "arguments": json.dumps({
                        "channel": "telegram",
                        "chat_id": "8775031757",
                        "content": "Steve — Glyn's been showing a noticeable mood dip this afternoon.",
                    }),
                },
            }],
            "timestamp": now_iso,
        },
    ])
    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="mood dip")
    assert "mood dip" in out
    assert "tool:message" in out


# ---- regex fallback ----------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_regex_falls_back_to_literal(workspace: Path, now_iso: str) -> None:
    _write_session(workspace, "t_x", [
        {"role": "user", "content": "the price was $5 (tax)", "timestamp": now_iso},
    ])
    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="$5 (")
    assert "tax" in out


# ---- malformed lines don't blow up -------------------------------------------


@pytest.mark.asyncio
async def test_handles_malformed_jsonl(workspace: Path, now_iso: str) -> None:
    sessions_dir = workspace / "sessions"
    sessions_dir.mkdir(parents=True)
    path = sessions_dir / "t_x.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"role": "user", "content": "good line", "timestamp": "' + now_iso + '"}\n')
        f.write('this is not json\n')
        f.write('{"role": "assistant", "content": "another good line", "timestamp": "' + now_iso + '"}\n')

    tool = SessionSearchTool(workspace=workspace)
    out = await tool.execute(query="good line")
    assert "good line" in out
    assert "another good line" in out
