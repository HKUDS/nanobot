"""Tests for MemoryStore: chunking, keyword search, summary, tokenizer, context building."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from nanobot.agent.memory import MemoryStore, Chunk
from nanobot.agent.context import ContextBuilder
from nanobot.config.schema import MemoryConfig


# ============================================================================
# Chunking
# ============================================================================


def test_chunk_memory_file_by_lines(memory_file):
    """Each `- [tag] ...` line in MEMORY.md becomes an independent chunk."""
    store = MemoryStore(memory_file)
    chunks = store._build_chunks()

    # Filter to only MEMORY.md chunks
    mem_chunks = [c for c in chunks if "MEMORY.md" in c.path]

    assert len(mem_chunks) == 7  # 7 bullet lines in fixture
    # Verify sections are tracked
    sections = {c.section for c in mem_chunks}
    assert "## User" in sections
    assert "## Preferences" in sections
    assert "## Projects" in sections

    # Each chunk is a single line
    for c in mem_chunks:
        assert c.start_line == c.end_line
        assert c.text.startswith("- [")


def test_chunk_daily_file_by_paragraphs(daily_notes):
    """Daily notes are chunked by paragraphs (blank-line separated)."""
    store = MemoryStore(daily_notes)
    chunks = store._build_chunks()

    # Filter to 2026-02-08 chunks
    day_chunks = [c for c in chunks if "2026-02-08" in c.path]

    # The fixture has: title paragraph, docker paragraph, memory paragraph
    assert len(day_chunks) == 3

    # Docker paragraph should contain both lines
    docker_chunk = [c for c in day_chunks if "Docker" in c.text][0]
    assert "nginx" in docker_chunk.text
    assert docker_chunk.start_line < docker_chunk.end_line


def test_chunk_empty_workspace(workspace):
    """Empty workspace returns no chunks."""
    store = MemoryStore(workspace)
    chunks = store._build_chunks()
    assert chunks == []


def test_chunk_empty_memory_file(workspace):
    """MEMORY.md with only headers and no entries returns no chunks."""
    (workspace / "memory" / "MEMORY.md").write_text("# Long-term Memory\n\n## User\n\n## Notes\n")
    store = MemoryStore(workspace)
    chunks = store._build_chunks()
    assert chunks == []


def test_chunk_mixed_files(memory_file, daily_notes):
    """Both MEMORY.md and daily notes are scanned together."""
    # memory_file and daily_notes share the same workspace via fixture chain
    store = MemoryStore(memory_file)
    chunks = store._build_chunks()

    paths = {c.path for c in chunks}
    assert any("MEMORY.md" in p for p in paths)
    assert any("2026-02-08" in p for p in paths)
    assert any("2026-02-07" in p for p in paths)


# ============================================================================
# Tokenizer
# ============================================================================


def test_tokenize_english():
    tokens = MemoryStore._tokenize("hello world test")
    assert tokens == ["hello", "world", "test"]


def test_tokenize_cjk():
    tokens = MemoryStore._tokenize("用户偏好")
    assert "用" in tokens
    assert "户" in tokens
    assert "偏" in tokens
    assert "好" in tokens


def test_tokenize_mixed():
    tokens = MemoryStore._tokenize("user偏好Python")
    assert "user" in tokens
    assert "偏" in tokens
    assert "好" in tokens
    assert "python" in tokens


def test_tokenize_empty():
    tokens = MemoryStore._tokenize("")
    assert tokens == []


# ============================================================================
# Keyword search
# ============================================================================


async def test_keyword_search_basic(memory_file):
    """Keyword search finds matching chunks and ranks by hit count."""
    store = MemoryStore(memory_file)
    results = await store.search("Python JavaScript", max_results=5)

    assert len(results) >= 1
    # The preference about Python/JavaScript should be top result
    assert "Python" in results[0].text
    assert results[0].score > 0


async def test_keyword_search_no_match(memory_file):
    """Query with no matching keywords returns empty."""
    store = MemoryStore(memory_file)
    results = await store.search("quantum computing blockchain", max_results=5)
    assert results == []


async def test_keyword_search_cjk(workspace):
    """Chinese keywords match Chinese content."""
    (workspace / "memory" / "MEMORY.md").write_text(
        "# Memory\n\n## User\n- [fact] 用户在上海工作\n- [fact] 用户喜欢编程\n"
    )
    store = MemoryStore(workspace)
    results = await store.search("上海", max_results=5)

    assert len(results) >= 1
    assert "上海" in results[0].text


async def test_keyword_search_max_results(memory_file):
    """max_results limits the number of returned results."""
    store = MemoryStore(memory_file)
    # "User" appears in many chunks
    results = await store.search("User", max_results=2)
    assert len(results) <= 2


async def test_keyword_search_case_insensitive(memory_file):
    """Search is case-insensitive."""
    store = MemoryStore(memory_file)
    results_lower = await store.search("python", max_results=5)
    results_upper = await store.search("PYTHON", max_results=5)

    assert len(results_lower) == len(results_upper)
    if results_lower:
        assert results_lower[0].text == results_upper[0].text


# ============================================================================
# Summary (progressive disclosure)
# ============================================================================


def test_get_memory_summary_small_file(workspace):
    """Small MEMORY.md is returned in full."""
    content = "# Memory\n\n## User\n- [fact] Test fact\n"
    (workspace / "memory" / "MEMORY.md").write_text(content)
    store = MemoryStore(workspace)

    summary = store.get_memory_summary(max_lines=20)
    assert summary == content


def test_get_memory_summary_large_file(workspace):
    """Large MEMORY.md is truncated with a hint."""
    lines = ["# Memory", ""] + [f"- [fact] Fact number {i}" for i in range(50)]
    content = "\n".join(lines)
    (workspace / "memory" / "MEMORY.md").write_text(content)
    store = MemoryStore(workspace)

    summary = store.get_memory_summary(max_lines=10)
    summary_lines = summary.splitlines()

    # Should have 10 content lines + 1 truncation hint
    assert len(summary_lines) == 11
    assert "more lines" in summary_lines[-1]
    assert "memory_search" in summary_lines[-1]


def test_get_memory_summary_empty(workspace):
    """No MEMORY.md returns empty string."""
    store = MemoryStore(workspace)
    assert store.get_memory_summary() == ""


def test_get_memory_context_combines_parts(memory_file):
    """get_memory_context includes summary + today's notes + search hint."""
    store = MemoryStore(memory_file)
    # Write today's note
    store.append_today("Had a productive meeting.")

    context = store.get_memory_context()

    assert "Long-term Memory (summary)" in context
    assert "Today's Notes" in context
    assert "memory_search" in context


# ============================================================================
# Query-aware retrieval (ContextBuilder)
# ============================================================================


async def test_build_system_prompt_with_user_message(memory_file):
    """Relevant memories appear in prompt when user_message is provided."""
    ctx = ContextBuilder(memory_file, memory_config=MemoryConfig())

    prompt = await ctx.build_system_prompt(user_message="What do I prefer Python or JS?")

    assert "Relevant Memories" in prompt
    assert "Python" in prompt


async def test_build_system_prompt_without_user_message(memory_file):
    """No extra search is performed when user_message is empty."""
    ctx = ContextBuilder(memory_file, memory_config=MemoryConfig())

    with patch.object(ctx.memory, "search", new_callable=AsyncMock) as mock_search:
        prompt = await ctx.build_system_prompt(user_message="")
        mock_search.assert_not_called()

    # Should still have the static memory summary
    assert "Memory" in prompt


async def test_build_system_prompt_no_relevant_results(workspace):
    """Graceful handling when query-aware search returns no results."""
    ctx = ContextBuilder(workspace, memory_config=MemoryConfig())

    # No MEMORY.md, no daily notes — search returns empty
    prompt = await ctx.build_system_prompt(user_message="quantum computing")

    # Should not crash, should not have "Relevant Memories" section
    assert "Relevant Memories" not in prompt
    assert "nanobot" in prompt  # Still has identity section
