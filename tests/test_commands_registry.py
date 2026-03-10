"""Tests for CommandRegistry."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from nanobot.agent.commands import (
    CommandRegistry,
    CommandContext,
    CommandResult,
    create_help_handler,
)


class TestCommandRegistry:
    """Tests for CommandRegistry class."""

    def test_register_command(self) -> None:
        """Should register a command handler."""
        registry = CommandRegistry()
        handler = AsyncMock()

        registry.register("test", handler, "Test command")

        assert registry.get_handler("test") is handler

    def test_register_immediate_command(self) -> None:
        """Should mark command as immediate when specified."""
        registry = CommandRegistry()
        handler = AsyncMock()

        registry.register("stop", handler, "Stop current task", immediate=True)

        assert registry.is_immediate("stop") is True
        assert registry.is_immediate("test") is False

    def test_get_handler_not_found(self) -> None:
        """Should return None for unknown commands."""
        registry = CommandRegistry()

        assert registry.get_handler("unknown") is None

    def test_is_immediate_not_found(self) -> None:
        """Should return False for unknown commands."""
        registry = CommandRegistry()

        assert registry.is_immediate("unknown") is False

    def test_get_help_text_single_command(self) -> None:
        """Should generate help text for single command."""
        registry = CommandRegistry()
        handler = AsyncMock()
        registry.register("help", handler, "Show help")

        help_text = registry.get_help_text()

        assert "help" in help_text
        assert "Show help" in help_text

    def test_get_help_text_multiple_commands(self) -> None:
        """Should generate help text for multiple commands."""
        registry = CommandRegistry()
        registry.register("new", AsyncMock(), "Start new session")
        registry.register("help", AsyncMock(), "Show help")

        help_text = registry.get_help_text()

        assert "new" in help_text
        assert "help" in help_text
        assert "nanobot commands" in help_text


class TestCommandContext:
    """Tests for CommandContext dataclass."""

    def test_command_context_creation(self) -> None:
        """Should create CommandContext with all fields."""
        msg = MagicMock()
        session = MagicMock()
        agent = MagicMock()

        context = CommandContext(
            message=msg,
            session=session,
            agent=agent,
        )

        assert context.message is msg
        assert context.session is session
        assert context.agent is agent


class TestCommandResult:
    """Tests for CommandResult."""

    def test_command_result_with_content(self) -> None:
        """Should create CommandResult with content."""
        result = CommandResult(content="Hello")

        assert result.content == "Hello"
        assert result.response is None

    def test_command_result_with_response(self) -> None:
        """Should create CommandResult with response."""
        response = MagicMock()

        result = CommandResult(response=response)

        assert result.response is response
        assert result.content is None

    def test_command_result_default_response_needed(self) -> None:
        """Should default response_needed to True."""
        result = CommandResult(content="Hello")

        assert result.response_needed is True

    def test_command_result_response_needed_false(self) -> None:
        """Should allow setting response_needed to False."""
        result = CommandResult(content="Hello", response_needed=False)

        assert result.response_needed is False


class TestHelpHandler:
    """Tests for help command handler."""

    @pytest.mark.asyncio
    async def test_help_handler_returns_help_text(self) -> None:
        """Should return help text from registry."""
        registry = CommandRegistry()
        registry.register("new", AsyncMock(), "Start new session")
        registry.register("help", AsyncMock(), "Show help")

        # Patch the global registry
        import nanobot.agent.commands as commands_module
        original_registry = commands_module._registry
        commands_module._registry = registry

        try:
            handler = create_help_handler()
            msg = MagicMock()
            msg.channel = "cli"
            msg.chat_id = "direct"
            context = CommandContext(message=msg)

            result = await handler(context)

            assert result is not None
            assert "nanobot commands" in result.content
            assert "new" in result.content
        finally:
            commands_module._registry = original_registry


class TestNewHandler:
    """Tests for new command handler."""

    @pytest.mark.asyncio
    async def test_new_handler_success(self) -> None:
        """Should return success message when session cleared."""
        from nanobot.agent.commands import create_new_handler

        # Create mocks
        msg = MagicMock()
        msg.channel = "cli"
        msg.chat_id = "direct"

        session = MagicMock()
        session.key = "cli:direct"
        session.messages = []
        session.last_consolidated = 0

        agent = MagicMock()
        agent.sessions.get_or_create.return_value = session
        agent.sessions.save = MagicMock()
        agent.sessions.invalidate = MagicMock()
        agent._consolidating = set()
        agent._consolidation_locks = {}
        agent._consolidate_memory = AsyncMock(return_value=True)

        context = CommandContext(message=msg, session=session, agent=agent)

        handler = create_new_handler()
        result = await handler(context)

        assert result is not None
        assert "New session started" in result.content
        session.clear.assert_called_once()
        agent.sessions.save.assert_called_once_with(session)
        agent.sessions.invalidate.assert_called_once_with(session.key)

    @pytest.mark.asyncio
    async def test_new_handler_archive_failure(self) -> None:
        """Should return error message when archive fails."""
        from nanobot.agent.commands import create_new_handler

        msg = MagicMock()
        msg.channel = "cli"
        msg.chat_id = "direct"

        session = MagicMock()
        session.key = "cli:direct"
        session.messages = ["msg1", "msg2"]
        session.last_consolidated = 0

        agent = MagicMock()
        agent.sessions.get_or_create.return_value = session
        agent._consolidating = set()
        agent._consolidation_locks = {}
        agent._consolidate_memory = AsyncMock(return_value=False)

        context = CommandContext(message=msg, session=session, agent=agent)

        handler = create_new_handler()
        result = await handler(context)

        assert result is not None
        assert "failed" in result.content.lower()
        session.clear.assert_not_called()
