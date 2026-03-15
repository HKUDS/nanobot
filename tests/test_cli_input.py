import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.formatted_text import ANSI, HTML

from nanobot.cli import commands


@pytest.fixture
def mock_prompt_session():
    """Mock the global prompt session."""
    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock()
    with patch("nanobot.cli.commands._PROMPT_SESSION", mock_session), \
         patch("nanobot.cli.commands.patch_stdout"):
        yield mock_session


@pytest.mark.asyncio
async def test_read_interactive_input_async_returns_input(mock_prompt_session):
    """Test that _read_interactive_input_async returns the user input from prompt_session."""
    mock_prompt_session.prompt_async.return_value = "hello world"

    result = await commands._read_interactive_input_async()
    
    assert result == "hello world"
    mock_prompt_session.prompt_async.assert_called_once()
    args, _ = mock_prompt_session.prompt_async.call_args
    assert isinstance(args[0], HTML)  # Verify HTML prompt is used


@pytest.mark.asyncio
async def test_read_interactive_input_async_handles_eof(mock_prompt_session):
    """Test that EOFError converts to KeyboardInterrupt."""
    mock_prompt_session.prompt_async.side_effect = EOFError()

    with pytest.raises(KeyboardInterrupt):
        await commands._read_interactive_input_async()


def test_init_prompt_session_creates_session():
    """Test that _init_prompt_session initializes the global session."""
    # Ensure global is None before test
    commands._PROMPT_SESSION = None
    
    with patch("nanobot.cli.commands.PromptSession") as MockSession, \
         patch("nanobot.cli.commands.FileHistory") as MockHistory, \
         patch("pathlib.Path.home") as mock_home:
        
        mock_home.return_value = MagicMock()
        
        commands._init_prompt_session()
        
        assert commands._PROMPT_SESSION is not None
        MockSession.assert_called_once()
        _, kwargs = MockSession.call_args
        assert kwargs["multiline"] is False
        assert kwargs["enable_open_in_editor"] is False


def test_print_agent_response_uses_console_without_name_error():
    """Regression test for NameError in _print_agent_response."""
    mock_console = MagicMock()
    with patch("nanobot.cli.commands._make_console", return_value=mock_console):
        commands._print_agent_response("hello", render_markdown=True)
    assert mock_console.print.call_count == 4


class _PromptTeamManager:
    def has_active_team(self, _sk):
        return True

    def active_team_id(self, _sk):
        return "nano-x"

    def list_members(self, _sk):
        return ["lead"]

    def get_member_snapshot(self, _sk, _name):
        return None

    def get_board_snapshot(self, _sk):
        return {
            "team_id": "nano-x",
            "status": "active",
            "members": [{"name": "lead", "status": "active", "task": "msg -> *"}],
            "tasks": [],
            "approvals": [],
            "recent_updates": [],
        }


def test_prompt_message_suppresses_board_once_for_btw():
    tm = _PromptTeamManager()
    commands._sync_team_view(tm)
    commands._TEAM_VIEW.suppress_board_once = True
    first = commands._prompt_message(tm)
    second = commands._prompt_message(tm)
    assert isinstance(first, HTML)
    assert isinstance(second, ANSI)
