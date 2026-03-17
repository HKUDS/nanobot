"""Tests for memory poisoning and prompt injection hardening."""

from pathlib import Path

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.session.manager import Session, SessionManager


# --- Protected file enforcement ---


async def test_write_tool_blocks_protected_file(tmp_path: Path) -> None:
    protected = tmp_path / "SOUL.md"
    protected.write_text("original", encoding="utf-8")

    tool = WriteFileTool(workspace=tmp_path, protected_patterns=["SOUL.md"])
    result = await tool.execute(path=str(protected), content="pwned")

    assert "protected" in result.lower()
    assert protected.read_text() == "original"


async def test_edit_tool_blocks_protected_file(tmp_path: Path) -> None:
    protected = tmp_path / "AGENTS.md"
    protected.write_text("safe content", encoding="utf-8")

    tool = EditFileTool(workspace=tmp_path, protected_patterns=["AGENTS.md"])
    result = await tool.execute(path=str(protected), old_text="safe", new_text="pwned")

    assert "protected" in result.lower()
    assert "safe content" in protected.read_text()


async def test_write_tool_allows_unprotected_file(tmp_path: Path) -> None:
    tool = WriteFileTool(workspace=tmp_path, protected_patterns=["SOUL.md"])
    result = await tool.execute(path=str(tmp_path / "notes.md"), content="hello")

    assert "Successfully wrote" in result


async def test_protected_patterns_match_nested_paths(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / "IDENTITY.md"
    nested.parent.mkdir()
    nested.write_text("original", encoding="utf-8")

    tool = WriteFileTool(workspace=tmp_path, protected_patterns=["IDENTITY.md"])
    result = await tool.execute(path=str(nested), content="pwned")

    assert "protected" in result.lower()


# --- Memory size limits ---


def test_memory_truncates_at_limit(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    big_content = "\n".join(f"line {i}" for i in range(300))
    store.write_long_term(big_content)

    saved = store.read_long_term()
    assert "[Truncated" in saved
    assert saved.count("\n") <= store._MAX_MEMORY_LINES + 5


def test_history_trims_oldest_entries(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path)
    # Write enough entries to exceed limit
    for i in range(store._MAX_HISTORY_LINES + 100):
        store.append_history(f"[2026-01-01 00:{i:02d}] entry {i}")

    lines = store.history_file.read_text().splitlines()
    assert len(lines) <= store._MAX_HISTORY_LINES + 5


# --- Session size limits ---


def test_session_save_trims_excess_messages(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path, max_messages=100)
    session = Session(key="test:trim")
    for i in range(200):
        session.add_message("user", f"msg {i}")
    session.last_consolidated = 50

    mgr.save(session)

    assert len(session.messages) == 100
    assert session.last_consolidated == 0  # 50 - 100 trimmed, clamped to 0


def test_session_save_preserves_small_sessions(tmp_path: Path) -> None:
    mgr = SessionManager(tmp_path, max_messages=100)
    session = Session(key="test:small")
    for i in range(50):
        session.add_message("user", f"msg {i}")

    mgr.save(session)

    assert len(session.messages) == 50
