import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from nanobot.agent.tools.claude_code import ClaudeCodeTool, TMUX_SOCKET, _generate_id


# ── Helpers ──────────────────────────────────────────────────────────


def _make_tool(tmp_path: Path) -> ClaudeCodeTool:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return ClaudeCodeTool(workspace)


def _seed_sessions(tool: ClaudeCodeTool, sessions: list[dict]) -> None:
    tool._storage_dir.mkdir(parents=True, exist_ok=True)
    tool._storage_file.write_text(json.dumps(sessions))


def _read_sessions(tool: ClaudeCodeTool) -> list[dict]:
    return json.loads(tool._storage_file.read_text())


# ── Properties & Schema ─────────────────────────────────────────────


def test_tool_name_and_description(tmp_path):
    tool = _make_tool(tmp_path)
    assert tool.name == "claude_code"
    assert "create" in tool.description
    assert "list" in tool.description
    assert "resume" in tool.description


def test_to_schema(tmp_path):
    tool = _make_tool(tmp_path)
    schema = tool.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "claude_code"
    assert "action" in schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["action"]


def test_set_context(tmp_path):
    tool = _make_tool(tmp_path)
    tool.set_context("telegram", "12345")
    assert tool._channel == "telegram"
    assert tool._chat_id == "12345"


# ── generate_id ──────────────────────────────────────────────────────


def test_generate_id_format():
    sid = _generate_id()
    assert sid.startswith("cc-")
    parts = sid.split("-")
    # cc-YYYYMMDD-HHMMSS-random6
    assert len(parts) == 4
    assert len(parts[1]) == 8  # YYYYMMDD
    assert len(parts[2]) == 6  # HHMMSS
    assert len(parts[3]) == 6  # random


# ── Storage ──────────────────────────────────────────────────────────


def test_load_sessions_missing_file(tmp_path):
    tool = _make_tool(tmp_path)
    assert tool._load_sessions() == []


def test_load_sessions_corrupt_json(tmp_path):
    tool = _make_tool(tmp_path)
    tool._storage_dir.mkdir(parents=True, exist_ok=True)
    tool._storage_file.write_text("not json")
    assert tool._load_sessions() == []


def test_load_sessions_non_list_json(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [])
    tool._storage_file.write_text(json.dumps({"not": "a list"}))
    assert tool._load_sessions() == []


def test_save_and_load_roundtrip(tmp_path):
    tool = _make_tool(tmp_path)
    data = [{"id": "cc-test", "purpose": "test"}]
    tool._save_sessions(data)
    assert tool._load_sessions() == data


# ── Create ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_validates_workspace(tmp_path):
    tool = _make_tool(tmp_path)
    result = await tool.execute(action="create", workspace_path="/nonexistent/path")
    assert result.startswith("Error:")
    assert "does not exist" in result


@pytest.mark.asyncio
async def test_create_session_success(tmp_path):
    tool = _make_tool(tmp_path)
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    with (
        patch.object(ClaudeCodeTool, "_ensure_tmux_socket_dir"),
        patch("subprocess.run") as mock_run,
        patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        result = await tool.execute(
            action="create",
            purpose="Fix bug",
            workspace_path=str(work_dir),
        )

    assert "Created Claude Code session" in result
    assert "Fix bug" in result
    assert str(work_dir) in result
    assert "tmux session: claude-cc-" in result

    # Verify session was persisted
    sessions = _read_sessions(tool)
    assert len(sessions) == 1
    assert sessions[0]["purpose"] == "Fix bug"
    assert sessions[0]["status"] == "active"
    assert sessions[0]["workspace_path"] == str(work_dir)


@pytest.mark.asyncio
async def test_create_session_with_message(tmp_path):
    tool = _make_tool(tmp_path)
    work_dir = tmp_path / "project"
    work_dir.mkdir()

    with (
        patch.object(ClaudeCodeTool, "_ensure_tmux_socket_dir"),
        patch("subprocess.run") as mock_run,
        patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        await tool.execute(
            action="create",
            purpose="Run task",
            workspace_path=str(work_dir),
            message="Hello Claude!",
        )

    # Verify the tmux send-keys command included --message flag
    # call_args_list: [0] create session, [1] send-keys with command, [2] send Enter
    assert mock_run.call_count == 3
    send_keys_call = mock_run.call_args_list[1][0][0]
    assert "send-keys" in send_keys_call
    # The claude command with --message is in the send-keys args
    cmd_str = " ".join(send_keys_call)
    assert "--message" in cmd_str
    assert "Hello Claude!" in cmd_str


@pytest.mark.asyncio
async def test_create_default_workspace(tmp_path):
    tool = _make_tool(tmp_path)

    with (
        patch.object(ClaudeCodeTool, "_ensure_tmux_socket_dir"),
        patch("subprocess.run") as mock_run,
        patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        result = await tool.execute(action="create", purpose="General")

    # Should use tool's workspace as default
    sessions = _read_sessions(tool)
    assert sessions[0]["workspace_path"] == str(tool._workspace)


@pytest.mark.asyncio
async def test_create_default_purpose(tmp_path):
    tool = _make_tool(tmp_path)

    with (
        patch.object(ClaudeCodeTool, "_ensure_tmux_socket_dir"),
        patch("subprocess.run"),
        patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=True),
    ):
        await tool.execute(action="create")

    sessions = _read_sessions(tool)
    assert sessions[0]["purpose"] == "General session"


@pytest.mark.asyncio
async def test_create_tmux_timeout(tmp_path):
    tool = _make_tool(tmp_path)
    import subprocess

    with (
        patch.object(ClaudeCodeTool, "_ensure_tmux_socket_dir"),
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired("tmux", 10)),
    ):
        result = await tool.execute(action="create")

    assert "Error" in result
    assert "timed out" in result


@pytest.mark.asyncio
async def test_create_tmux_not_installed(tmp_path):
    tool = _make_tool(tmp_path)

    with (
        patch.object(ClaudeCodeTool, "_ensure_tmux_socket_dir"),
        patch("subprocess.run", side_effect=FileNotFoundError),
    ):
        result = await tool.execute(action="create")

    assert "Error" in result
    assert "tmux is not installed" in result


@pytest.mark.asyncio
async def test_create_tmux_session_fails(tmp_path):
    tool = _make_tool(tmp_path)

    with (
        patch.object(ClaudeCodeTool, "_ensure_tmux_socket_dir"),
        patch("subprocess.run") as mock_run,
        patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=False),
    ):
        mock_run.return_value = MagicMock(returncode=1)
        result = await tool.execute(action="create")

    assert "Error" in result
    assert "failed to create" in result


@pytest.mark.asyncio
async def test_create_with_metadata(tmp_path):
    tool = _make_tool(tmp_path)

    with (
        patch.object(ClaudeCodeTool, "_ensure_tmux_socket_dir"),
        patch("subprocess.run"),
        patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=True),
    ):
        await tool.execute(
            action="create",
            purpose="With meta",
            metadata={"repo": "nanobot", "pr": 42},
        )

    sessions = _read_sessions(tool)
    assert sessions[0]["metadata"] == {"repo": "nanobot", "pr": 42}


# ── List ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_empty_sessions(tmp_path):
    tool = _make_tool(tmp_path)
    result = await tool.execute(action="list")
    assert "No Claude Code sessions found" in result


@pytest.mark.asyncio
async def test_list_sessions_shows_all(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-20260101-120000-abc123",
            "purpose": "Fix bug",
            "tmux_session_name": "claude-cc-20260101-120000-abc123",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
        {
            "id": "cc-20260102-120000-def456",
            "purpose": "Add feature",
            "tmux_session_name": "claude-cc-20260102-120000-def456",
            "status": "archived",
            "created_at_ms": 1735819200000,
            "last_used_at_ms": 1735819200000,
        },
    ])

    with patch.object(ClaudeCodeTool, "_list_tmux_sessions", return_value={"claude-cc-20260101-120000-abc123"}):
        result = await tool.execute(action="list")

    assert "Fix bug" in result
    assert "Add feature" in result
    assert "[active]" in result
    assert "[archived]" in result


@pytest.mark.asyncio
async def test_list_sessions_filter_by_status(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-1",
            "purpose": "Active one",
            "tmux_session_name": "claude-cc-1",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
        {
            "id": "cc-2",
            "purpose": "Archived one",
            "tmux_session_name": "claude-cc-2",
            "status": "archived",
            "created_at_ms": 1735819200000,
            "last_used_at_ms": 1735819200000,
        },
    ])

    with patch.object(ClaudeCodeTool, "_list_tmux_sessions", return_value={"claude-cc-1"}):
        result = await tool.execute(action="list", status="archived")

    assert "Archived one" in result
    assert "Active one" not in result


@pytest.mark.asyncio
async def test_list_no_sessions_matching_filter(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-1",
            "purpose": "Active one",
            "tmux_session_name": "claude-cc-1",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
    ])

    with patch.object(ClaudeCodeTool, "_list_tmux_sessions", return_value={"claude-cc-1"}):
        result = await tool.execute(action="list", status="archived")

    assert "No sessions with status 'archived'" in result


@pytest.mark.asyncio
async def test_list_syncs_status_with_tmux(tmp_path):
    """If tmux session is gone, status should update to detached."""
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-1",
            "purpose": "Was active",
            "tmux_session_name": "claude-cc-1",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
    ])

    # tmux reports no sessions (empty set)
    with patch.object(ClaudeCodeTool, "_list_tmux_sessions", return_value=set()):
        result = await tool.execute(action="list")

    assert "[detached]" in result
    sessions = _read_sessions(tool)
    assert sessions[0]["status"] == "detached"


@pytest.mark.asyncio
async def test_list_sorted_by_last_used(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-old",
            "purpose": "Old session",
            "tmux_session_name": "claude-cc-old",
            "status": "archived",
            "created_at_ms": 1000000000000,
            "last_used_at_ms": 1000000000000,
        },
        {
            "id": "cc-new",
            "purpose": "New session",
            "tmux_session_name": "claude-cc-new",
            "status": "active",
            "created_at_ms": 2000000000000,
            "last_used_at_ms": 2000000000000,
        },
    ])

    with patch.object(ClaudeCodeTool, "_list_tmux_sessions", return_value={"claude-cc-new"}):
        result = await tool.execute(action="list")

    # "New session" should appear before "Old session"
    new_pos = result.index("New session")
    old_pos = result.index("Old session")
    assert new_pos < old_pos


# ── Resume ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resume_requires_session_id(tmp_path):
    tool = _make_tool(tmp_path)
    result = await tool.execute(action="resume")
    assert "Error" in result
    assert "session_id is required" in result


@pytest.mark.asyncio
async def test_resume_no_sessions(tmp_path):
    tool = _make_tool(tmp_path)
    result = await tool.execute(action="resume", session_id="cc-missing")
    assert "Error" in result
    assert "no sessions found" in result


@pytest.mark.asyncio
async def test_resume_exact_match(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-20260101-120000-abc123",
            "purpose": "Fix bug",
            "workspace_path": "/tmp/project",
            "tmux_session_name": "claude-cc-20260101-120000-abc123",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
    ])

    with patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=True):
        result = await tool.execute(
            action="resume",
            session_id="cc-20260101-120000-abc123",
        )

    assert "is active" in result
    assert "Fix bug" in result
    # Verify timestamp was updated
    sessions = _read_sessions(tool)
    assert sessions[0]["last_used_at_ms"] > 1735732800000


@pytest.mark.asyncio
async def test_resume_fuzzy_match_by_partial_id(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-20260101-120000-abc123",
            "purpose": "Fix bug",
            "workspace_path": "/tmp/project",
            "tmux_session_name": "claude-cc-20260101-120000-abc123",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
    ])

    with patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=True):
        result = await tool.execute(action="resume", session_id="abc123")

    assert "is active" in result
    assert "Fix bug" in result


@pytest.mark.asyncio
async def test_resume_fuzzy_match_by_purpose(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-20260101-120000-abc123",
            "purpose": "Fix authentication bug",
            "workspace_path": "/tmp/project",
            "tmux_session_name": "claude-cc-20260101-120000-abc123",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
    ])

    with patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=True):
        result = await tool.execute(action="resume", session_id="authentication")

    assert "is active" in result
    assert "Fix authentication bug" in result


@pytest.mark.asyncio
async def test_resume_fuzzy_multiple_matches(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-1",
            "purpose": "Fix bug A",
            "workspace_path": "/tmp",
            "tmux_session_name": "claude-cc-1",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
        {
            "id": "cc-2",
            "purpose": "Fix bug B",
            "workspace_path": "/tmp",
            "tmux_session_name": "claude-cc-2",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
    ])

    result = await tool.execute(action="resume", session_id="Fix bug")
    assert "Multiple sessions match" in result
    assert "cc-1" in result
    assert "cc-2" in result


@pytest.mark.asyncio
async def test_resume_no_match(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-1",
            "purpose": "Fix bug",
            "workspace_path": "/tmp",
            "tmux_session_name": "claude-cc-1",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
    ])

    result = await tool.execute(action="resume", session_id="nonexistent")
    assert "Error" in result
    assert "no session found matching" in result


@pytest.mark.asyncio
async def test_resume_tmux_session_gone(tmp_path):
    tool = _make_tool(tmp_path)
    _seed_sessions(tool, [
        {
            "id": "cc-dead",
            "purpose": "Dead session",
            "workspace_path": "/tmp",
            "tmux_session_name": "claude-cc-dead",
            "status": "active",
            "created_at_ms": 1735732800000,
            "last_used_at_ms": 1735732800000,
        },
    ])

    with patch.object(ClaudeCodeTool, "_tmux_session_exists", return_value=False):
        result = await tool.execute(action="resume", session_id="cc-dead")

    assert "Error" in result
    assert "no longer running" in result
    assert "detached" in result

    # Verify status was updated to detached
    sessions = _read_sessions(tool)
    assert sessions[0]["status"] == "detached"


# ── Unknown action ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_action(tmp_path):
    tool = _make_tool(tmp_path)
    result = await tool.execute(action="delete")
    assert "Error" in result
    assert "Unknown action" in result


# ── Tmux helpers (static methods) ────────────────────────────────────


def test_tmux_session_exists_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert ClaudeCodeTool._tmux_session_exists("test-session") is True

    args = mock_run.call_args[0][0]
    assert args == ["tmux", "-S", TMUX_SOCKET, "has-session", "-t", "test-session"]


def test_tmux_session_exists_not_found():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert ClaudeCodeTool._tmux_session_exists("missing") is False


def test_tmux_session_exists_timeout():
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("tmux", 5)):
        assert ClaudeCodeTool._tmux_session_exists("test") is False


def test_tmux_session_exists_no_tmux():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert ClaudeCodeTool._tmux_session_exists("test") is False


def test_list_tmux_sessions_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="claude-cc-1\nclaude-cc-2\n",
        )
        result = ClaudeCodeTool._list_tmux_sessions()
    assert result == {"claude-cc-1", "claude-cc-2"}


def test_list_tmux_sessions_empty():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = ClaudeCodeTool._list_tmux_sessions()
    assert result == set()


def test_list_tmux_sessions_timeout():
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("tmux", 5)):
        result = ClaudeCodeTool._list_tmux_sessions()
    assert result == set()


def test_list_tmux_sessions_no_tmux():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = ClaudeCodeTool._list_tmux_sessions()
    assert result == set()


# ── Param validation ────────────────────────────────────────────────


def test_validate_params_requires_action(tmp_path):
    tool = _make_tool(tmp_path)
    errors = tool.validate_params({})
    assert any("action" in e for e in errors)


def test_validate_params_rejects_invalid_action(tmp_path):
    tool = _make_tool(tmp_path)
    errors = tool.validate_params({"action": "destroy"})
    assert any("must be one of" in e for e in errors)


def test_validate_params_accepts_valid_action(tmp_path):
    tool = _make_tool(tmp_path)
    for action in ("create", "list", "resume"):
        errors = tool.validate_params({"action": action})
        assert errors == []
