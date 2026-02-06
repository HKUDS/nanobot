"""Tests for TmuxTool."""

from unittest.mock import patch

import pytest

from nanobot.agent.tools.tmux import TmuxTool, _TmuxResult


@pytest.fixture
def tmux_tool() -> TmuxTool:
    """Create a TmuxTool instance."""
    return TmuxTool()


def _ok_result(stdout: bytes = b"", stderr: bytes = b"") -> _TmuxResult:
    """Helper to build a successful _TmuxResult."""
    return _TmuxResult(returncode=0, stdout=stdout, stderr=stderr)


def _err_result(stderr: bytes = b"error") -> _TmuxResult:
    """Helper to build a failed _TmuxResult."""
    return _TmuxResult(returncode=1, stdout=b"", stderr=stderr)


class TestTmuxToolSchema:
    """Tests for tool metadata."""

    def test_name(self, tmux_tool: TmuxTool) -> None:
        assert tmux_tool.name == "tmux"

    def test_description(self, tmux_tool: TmuxTool) -> None:
        assert "tmux" in tmux_tool.description.lower()

    def test_parameters_has_action(self, tmux_tool: TmuxTool) -> None:
        params = tmux_tool.parameters
        assert "action" in params["properties"]
        assert params["properties"]["action"]["enum"] == [
            "create",
            "send",
            "read",
            "list",
            "kill",
        ]

    def test_action_is_required(self, tmux_tool: TmuxTool) -> None:
        params = tmux_tool.parameters
        assert "action" in params["required"]

    def test_parameters_has_session_name(self, tmux_tool: TmuxTool) -> None:
        params = tmux_tool.parameters
        assert "session_name" in params["properties"]

    def test_parameters_has_command(self, tmux_tool: TmuxTool) -> None:
        params = tmux_tool.parameters
        assert "command" in params["properties"]

    def test_parameters_has_lines(self, tmux_tool: TmuxTool) -> None:
        params = tmux_tool.parameters
        assert "lines" in params["properties"]


class TestTmuxNotInstalled:
    """Tests for when tmux is not on PATH."""

    @pytest.mark.asyncio
    async def test_error_when_tmux_missing(self, tmux_tool: TmuxTool) -> None:
        with patch("shutil.which", return_value=None):
            result = await tmux_tool.execute(action="list")
            assert "not installed" in result.lower() or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_all_actions_fail_without_tmux(self, tmux_tool: TmuxTool) -> None:
        with patch("shutil.which", return_value=None):
            for action in ("create", "send", "read", "list", "kill"):
                result = await tmux_tool.execute(action=action)
                assert "error" in result.lower()


class TestTmuxCreate:
    """Tests for create action."""

    @pytest.mark.asyncio
    async def test_create_session(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(tmux_tool, "_run_tmux", return_value=_ok_result()),
        ):
            result = await tmux_tool.execute(action="create", session_name="test")
            assert "created" in result.lower()
            assert "test" in result

    @pytest.mark.asyncio
    async def test_create_requires_session_name(self, tmux_tool: TmuxTool) -> None:
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            result = await tmux_tool.execute(action="create")
            assert "error" in result.lower()
            assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_create_failure(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(
                tmux_tool,
                "_run_tmux",
                return_value=_err_result(b"duplicate session"),
            ),
        ):
            result = await tmux_tool.execute(action="create", session_name="test")
            assert "error" in result.lower()
            assert "duplicate session" in result


class TestTmuxSend:
    """Tests for send action."""

    @pytest.mark.asyncio
    async def test_send_command(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(tmux_tool, "_run_tmux", return_value=_ok_result()),
        ):
            result = await tmux_tool.execute(
                action="send",
                session_name="test",
                command="echo hello",
            )
            assert "sent" in result.lower()
            assert "test" in result

    @pytest.mark.asyncio
    async def test_send_requires_session_name(self, tmux_tool: TmuxTool) -> None:
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            result = await tmux_tool.execute(action="send", command="echo hello")
            assert "error" in result.lower()
            assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_send_requires_command(self, tmux_tool: TmuxTool) -> None:
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            result = await tmux_tool.execute(action="send", session_name="test")
            assert "error" in result.lower()
            assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_send_failure(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(
                tmux_tool,
                "_run_tmux",
                return_value=_err_result(b"session not found"),
            ),
        ):
            result = await tmux_tool.execute(
                action="send",
                session_name="test",
                command="echo hello",
            )
            assert "error" in result.lower()


class TestTmuxRead:
    """Tests for read action."""

    @pytest.mark.asyncio
    async def test_read_output(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(
                tmux_tool,
                "_run_tmux",
                return_value=_ok_result(b"hello world\n"),
            ),
        ):
            result = await tmux_tool.execute(action="read", session_name="test")
            assert "hello world" in result

    @pytest.mark.asyncio
    async def test_read_empty_output(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(tmux_tool, "_run_tmux", return_value=_ok_result(b"\n\n")),
        ):
            result = await tmux_tool.execute(action="read", session_name="test")
            assert result == "(no output)"

    @pytest.mark.asyncio
    async def test_read_requires_session_name(self, tmux_tool: TmuxTool) -> None:
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            result = await tmux_tool.execute(action="read")
            assert "error" in result.lower()
            assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_read_failure(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(
                tmux_tool,
                "_run_tmux",
                return_value=_err_result(b"session not found"),
            ),
        ):
            result = await tmux_tool.execute(action="read", session_name="test")
            assert "error" in result.lower()


class TestTmuxList:
    """Tests for list action."""

    @pytest.mark.asyncio
    async def test_list_sessions(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(
                tmux_tool,
                "_run_tmux",
                return_value=_ok_result(b"test: 1 windows\n"),
            ),
        ):
            result = await tmux_tool.execute(action="list")
            assert "test" in result

    @pytest.mark.asyncio
    async def test_list_no_server(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(
                tmux_tool,
                "_run_tmux",
                return_value=_err_result(b"no server running"),
            ),
        ):
            result = await tmux_tool.execute(action="list")
            assert "no active sessions" in result.lower()

    @pytest.mark.asyncio
    async def test_list_empty_output(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(tmux_tool, "_run_tmux", return_value=_ok_result(b"")),
        ):
            result = await tmux_tool.execute(action="list")
            assert "no active sessions" in result.lower()


class TestTmuxKill:
    """Tests for kill action."""

    @pytest.mark.asyncio
    async def test_kill_session(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(tmux_tool, "_run_tmux", return_value=_ok_result()),
        ):
            result = await tmux_tool.execute(action="kill", session_name="test")
            assert "killed" in result.lower()
            assert "test" in result

    @pytest.mark.asyncio
    async def test_kill_requires_session_name(self, tmux_tool: TmuxTool) -> None:
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            result = await tmux_tool.execute(action="kill")
            assert "error" in result.lower()
            assert "required" in result.lower()

    @pytest.mark.asyncio
    async def test_kill_failure(self, tmux_tool: TmuxTool) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/tmux"),
            patch.object(
                tmux_tool,
                "_run_tmux",
                return_value=_err_result(b"session not found"),
            ),
        ):
            result = await tmux_tool.execute(action="kill", session_name="test")
            assert "error" in result.lower()


class TestTmuxInvalidAction:
    """Tests for unknown actions."""

    @pytest.mark.asyncio
    async def test_invalid_action(self, tmux_tool: TmuxTool) -> None:
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            result = await tmux_tool.execute(action="invalid")
            assert "error" in result.lower()
            assert "unknown" in result.lower()
