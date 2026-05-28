"""Tests for the typed memory M1 slice: daily notes + memory_search / memory_get tools.

Daily notes back up MEMORY.md / HISTORY.md against the lossy summariser. The
LLM-driven consolidate() is exercised elsewhere; here we test the raw-write
side-effect and the two query tools.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.memory import MemoryGetTool, MemorySearchTool


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def store(workspace: Path) -> MemoryStore:
    return MemoryStore(workspace)


# ---- write_daily / list_daily_files -----------------------------------------


def test_write_daily_creates_file_for_today(store: MemoryStore) -> None:
    path = store.write_daily("hello world")
    assert path.exists()
    assert path.name == f"{datetime.now().strftime('%Y-%m-%d')}.md"
    content = path.read_text(encoding="utf-8")
    assert "## " in content              # heading present
    assert "consolidation" in content    # heading tag
    assert "hello world" in content


def test_write_daily_appends_within_same_day(store: MemoryStore) -> None:
    store.write_daily("entry one")
    store.write_daily("entry two")
    content = store._daily_file().read_text(encoding="utf-8")
    assert content.count("## ") == 2
    assert "entry one" in content
    assert "entry two" in content


def test_write_daily_separate_files_per_day(store: MemoryStore) -> None:
    when_a = datetime(2026, 5, 26, 10, 0)
    when_b = datetime(2026, 5, 27, 11, 0)
    p_a = store.write_daily("A", when=when_a)
    p_b = store.write_daily("B", when=when_b)
    assert p_a != p_b
    assert p_a.name == "2026-05-26.md"
    assert p_b.name == "2026-05-27.md"


def test_list_daily_files_filters_by_window(store: MemoryStore) -> None:
    now = datetime.now()
    store.write_daily("recent", when=now)
    store.write_daily("week_ago", when=now - timedelta(days=7))
    store.write_daily("old", when=now - timedelta(days=60))
    # 30-day window should include the first two but not the third
    found = {p.stem for p in store.list_daily_files(days=30)}
    assert (now.strftime("%Y-%m-%d")) in found
    assert (now - timedelta(days=7)).strftime("%Y-%m-%d") in found
    assert (now - timedelta(days=60)).strftime("%Y-%m-%d") not in found


def test_list_daily_files_ignores_non_daily_markdown(store: MemoryStore) -> None:
    """MEMORY.md / HISTORY.md / random files should not appear in daily list."""
    (store.memory_dir / "MEMORY.md").write_text("durable", encoding="utf-8")
    (store.memory_dir / "HISTORY.md").write_text("log", encoding="utf-8")
    (store.memory_dir / "notes.md").write_text("misc", encoding="utf-8")
    store.write_daily("daily")
    names = [p.name for p in store.list_daily_files(days=30)]
    assert names == [store._daily_file().name]


# ---- MemorySearchTool --------------------------------------------------------


@pytest.mark.asyncio
async def test_search_finds_match_in_daily_note(workspace: Path, store: MemoryStore) -> None:
    store.write_daily("USER: Glyn had a panic attack with visual hallucinations")
    tool = MemorySearchTool(workspace=workspace)
    out = await tool.execute(query="visual hallucinations")
    assert "panic attack" in out
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in out  # filename appears in match


@pytest.mark.asyncio
async def test_search_case_insensitive(workspace: Path, store: MemoryStore) -> None:
    store.write_daily("Flight booking U22461 — Luton to Lisbon")
    tool = MemorySearchTool(workspace=workspace)
    out = await tool.execute(query="LISBON")
    assert "Lisbon" in out


@pytest.mark.asyncio
async def test_search_respects_window(workspace: Path, store: MemoryStore) -> None:
    now = datetime.now()
    store.write_daily("recent crisis", when=now)
    store.write_daily("old crisis", when=now - timedelta(days=60))
    tool = MemorySearchTool(workspace=workspace)
    out = await tool.execute(query="crisis", days=30)
    assert "recent crisis" in out
    assert "old crisis" not in out


@pytest.mark.asyncio
async def test_search_no_matches_reports_empty(workspace: Path, store: MemoryStore) -> None:
    store.write_daily("nothing relevant here")
    tool = MemorySearchTool(workspace=workspace)
    out = await tool.execute(query="unicorn")
    assert "No matches" in out


@pytest.mark.asyncio
async def test_search_no_files_reports_empty(workspace: Path) -> None:
    tool = MemorySearchTool(workspace=workspace)
    out = await tool.execute(query="anything")
    assert "No daily notes" in out


@pytest.mark.asyncio
async def test_search_regex_falls_back_to_literal_on_bad_pattern(workspace: Path, store: MemoryStore) -> None:
    store.write_daily("the price was $5 (tax included)")
    tool = MemorySearchTool(workspace=workspace)
    # `$5 (` is invalid as a regex; should fall back to literal substring
    out = await tool.execute(query="$5 (")
    assert "tax included" in out


# ---- MemoryGetTool -----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_today_file(workspace: Path, store: MemoryStore) -> None:
    store.write_daily("today's entry")
    tool = MemoryGetTool(workspace=workspace)
    out = await tool.execute(date="today")
    assert "today's entry" in out


@pytest.mark.asyncio
async def test_get_returns_explicit_date(workspace: Path, store: MemoryStore) -> None:
    when = datetime(2026, 4, 15, 10, 0)
    store.write_daily("crisis context", when=when)
    tool = MemoryGetTool(workspace=workspace)
    out = await tool.execute(date="2026-04-15")
    assert "crisis context" in out


@pytest.mark.asyncio
async def test_get_missing_date_reports_clearly(workspace: Path) -> None:
    tool = MemoryGetTool(workspace=workspace)
    out = await tool.execute(date="2026-01-01")
    assert "No daily note" in out


@pytest.mark.asyncio
async def test_get_invalid_date_format(workspace: Path) -> None:
    tool = MemoryGetTool(workspace=workspace)
    out = await tool.execute(date="last tuesday")
    assert "invalid date" in out.lower()


@pytest.mark.asyncio
async def test_get_yesterday(workspace: Path, store: MemoryStore) -> None:
    yesterday = datetime.now() - timedelta(days=1)
    store.write_daily("yesterday's entry", when=yesterday)
    tool = MemoryGetTool(workspace=workspace)
    out = await tool.execute(date="yesterday")
    assert "yesterday's entry" in out


# ---- write_daily wired into consolidate() ------------------------------------


@pytest.mark.asyncio
async def test_consolidate_writes_daily_note_even_when_llm_fails(workspace: Path) -> None:
    """The key invariant: raw daily notes are durable even when the LLM consolidator fails.
    This is the failure mode from Peewee 2026-05-27 — `LLM did not call save_memory`."""
    from nanobot.session.manager import Session

    store = MemoryStore(workspace)
    session = Session(key="telegram:test")
    for i in range(40):
        session.add_message("user" if i % 2 else "assistant", f"verbatim message body {i}")

    # Provider returns no tool calls — consolidator will skip.
    provider = MagicMock()
    response = MagicMock()
    response.has_tool_calls = False
    response.tool_calls = []
    provider.chat = AsyncMock(return_value=response)

    ok = await store.consolidate(session, provider, "test-model", memory_window=20)

    assert ok is False, "LLM-side consolidate should report failure"
    # But the raw daily note is on disk anyway
    today_file = store._daily_file()
    assert today_file.exists(), "daily note must be written before the LLM call"
    body = today_file.read_text(encoding="utf-8")
    assert "verbatim message body 0" in body
    assert "session=telegram:test" in body
