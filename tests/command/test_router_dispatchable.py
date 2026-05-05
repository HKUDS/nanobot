"""Tests for CommandRouter.is_dispatchable_command and mid-turn command interception."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.command.builtin import register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter


class TestIsDispatchableCommand:
    """Unit tests for the is_dispatchable_command() predicate."""

    @pytest.fixture()
    def router(self) -> CommandRouter:
        r = CommandRouter()
        register_builtin_commands(r)
        return r

    def test_exact_commands_match(self, router: CommandRouter) -> None:
        assert router.is_dispatchable_command("/new")
        assert router.is_dispatchable_command("/help")
        assert router.is_dispatchable_command("/dream")
        assert router.is_dispatchable_command("/dream-log")
        assert router.is_dispatchable_command("/dream-restore")

    def test_prefix_commands_match(self, router: CommandRouter) -> None:
        assert router.is_dispatchable_command("/dream-log abc123")
        assert router.is_dispatchable_command("/dream-restore def456")

    def test_priority_commands_not_matched(self, router: CommandRouter) -> None:
        # Priority commands are NOT in the dispatchable tiers — they are
        # handled by is_priority() separately.
        assert not router.is_dispatchable_command("/stop")
        assert not router.is_dispatchable_command("/restart")

    def test_regular_text_not_matched(self, router: CommandRouter) -> None:
        assert not router.is_dispatchable_command("hello")
        assert not router.is_dispatchable_command("what is 2+2?")
        assert not router.is_dispatchable_command("")

    def test_case_insensitive(self, router: CommandRouter) -> None:
        assert router.is_dispatchable_command("/NEW")
        assert router.is_dispatchable_command("/Help")

    def test_strips_whitespace(self, router: CommandRouter) -> None:
        assert router.is_dispatchable_command("  /new  ")

    def test_unknown_slash_command_not_matched(self, router: CommandRouter) -> None:
        assert not router.is_dispatchable_command("/unknown")
        assert not router.is_dispatchable_command("/foo bar")


class TestMidTurnCommandDispatchedDirectly:
    """Verify that commands matching is_dispatchable_command() are dispatched
    correctly when session=None (the mid-turn path)."""

    @pytest.fixture()
    def router(self) -> CommandRouter:
        r = CommandRouter()
        register_builtin_commands(r)
        return r

    @pytest.fixture()
    def fake_loop(self) -> MagicMock:
        loop = MagicMock()
        loop.sessions = MagicMock()
        loop.sessions.get_or_create = MagicMock(return_value=MagicMock(
            messages=[], last_consolidated=0, clear=MagicMock(),
        ))
        loop.sessions.save = MagicMock()
        loop.sessions.invalidate = MagicMock()
        loop._schedule_background = MagicMock()
        loop._cancel_active_tasks = AsyncMock(return_value=0)
        return loop

    @pytest.fixture()
    def fake_msg(self) -> MagicMock:
        msg = MagicMock()
        msg.channel = "test"
        msg.chat_id = "chat1"
        msg.content = "/new"
        msg.metadata = {}
        return msg

    @pytest.mark.asyncio
    async def test_new_dispatched_with_session_none(
        self, router: CommandRouter, fake_loop: MagicMock, fake_msg: MagicMock,
    ) -> None:
        """cmd_new works when session=None (mid-turn dispatch path)."""
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="test:chat1", raw="/new", loop=fake_loop,
        )
        result = await router.dispatch(ctx)
        assert result is not None
        assert "New session" in result.content
        fake_loop.sessions.get_or_create.assert_called_once_with("test:chat1")

    @pytest.mark.asyncio
    async def test_help_dispatched_with_session_none(
        self, router: CommandRouter, fake_loop: MagicMock, fake_msg: MagicMock,
    ) -> None:
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="test:chat1", raw="/help", loop=fake_loop,
        )
        result = await router.dispatch(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_prefix_command_args_populated(self, router: CommandRouter) -> None:
        """Prefix commands have args populated correctly in mid-turn path."""
        # Use a custom prefix handler to avoid needing full mock setup.
        custom = CommandRouter()
        captured_args = []

        async def fake_handler(ctx: CommandContext) -> None:
            captured_args.append(ctx.args)
            return None

        custom.prefix("/test ", fake_handler)

        ctx = CommandContext(
            msg=MagicMock(channel="test", chat_id="c1", metadata={}),
            session=None, key="test:c1", raw="/test hello world", loop=MagicMock(),
        )
        await custom.dispatch(ctx)
        assert captured_args == ["hello world"]

    @pytest.mark.asyncio
    async def test_non_command_returns_none(
        self, router: CommandRouter, fake_loop: MagicMock, fake_msg: MagicMock,
    ) -> None:
        """Regular text returns None from dispatch (not a command)."""
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="test:chat1", raw="hello world", loop=fake_loop,
        )
        result = await router.dispatch(ctx)
        assert result is None
