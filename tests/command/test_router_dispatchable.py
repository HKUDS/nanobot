"""Tests for CommandRouter.is_dispatchable_command and mid-turn command interception."""

from __future__ import annotations

from inspect import Parameter, signature
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.command.builtin import (
    builtin_command_starts_agent_turn,
    register_builtin_commands,
)
from nanobot.command.router import CommandContext, CommandRouter


def test_command_context_requires_loop_as_keyword_dependency() -> None:
    loop_parameter = signature(CommandContext).parameters["loop"]

    assert loop_parameter.kind is Parameter.KEYWORD_ONLY
    assert loop_parameter.default is Parameter.empty


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
        assert router.is_dispatchable_command("/model")
        assert router.is_dispatchable_command("/dream")
        assert router.is_dispatchable_command("/dream-log")
        assert router.is_dispatchable_command("/dream-restore")
        assert router.is_dispatchable_command("/dream-prompt")
        assert router.is_dispatchable_command("/goal")
        assert router.is_dispatchable_command("/pairing")

    def test_prefix_commands_match(self, router: CommandRouter) -> None:
        assert router.is_dispatchable_command("/dream-log abc123")
        assert router.is_dispatchable_command("/dream-restore def456")
        assert router.is_dispatchable_command("/dream-prompt init")
        assert router.is_dispatchable_command("/model fast")
        assert router.is_dispatchable_command("/goal migrate the database")
        assert router.is_dispatchable_command("/pairing list")
        assert router.is_dispatchable_command("/pairing approve CODE")
        assert router.is_dispatchable_command("/__shell pwd")

    def test_priority_commands_not_matched(self, router: CommandRouter) -> None:
        # Priority commands are NOT in the dispatchable tiers — they are
        # handled by is_priority() separately.
        assert not router.is_dispatchable_command("/stop")
        assert not router.is_dispatchable_command("/restart")

    def test_regular_text_not_matched(self, router: CommandRouter) -> None:
        assert not router.is_dispatchable_command("hello")
        assert not router.is_dispatchable_command("what is 2+2?")
        assert not router.is_dispatchable_command("!important is still ordinary text")
        assert not router.is_dispatchable_command("")

    def test_case_insensitive(self, router: CommandRouter) -> None:
        assert router.is_dispatchable_command("/NEW")
        assert router.is_dispatchable_command("/Help")
        assert router.is_dispatchable_command("/PAIRING")

    def test_strips_whitespace(self, router: CommandRouter) -> None:
        assert router.is_dispatchable_command("  /new  ")
        assert router.is_dispatchable_command("  /pairing list  ")

    def test_invalid_slash_commands_match_for_explicit_rejection(
        self, router: CommandRouter,
    ) -> None:
        assert router.is_dispatchable_command("/unknown")
        assert router.is_dispatchable_command("/foo bar")
        assert router.is_dispatchable_command("/status now")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("/status", False),
        ("/history 5", False),
        ("/goal", False),
        ("/goal migrate the database", True),
        ("regular prompt", True),
        ("!pwd", True),
    ],
)
def test_builtin_command_agent_turn_lifecycle(content: str, expected: bool) -> None:
    assert builtin_command_starts_agent_turn(content) is expected


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
        loop.schedule_background = MagicMock()
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
        assert result.channel == "test"
        assert result.chat_id == "chat1"
        assert result.metadata["render_as"] == "text"
        assert "/new" in result.content
        assert "/pairing [list|approve <code>|deny <code>|revoke <user_id>]" in result.content

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

    @pytest.mark.asyncio
    async def test_unknown_command_suggests_close_match(
        self, router: CommandRouter, fake_loop: MagicMock, fake_msg: MagicMock,
    ) -> None:
        fake_msg.content = "/neaw"
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="test:chat1", raw="/neaw", loop=fake_loop,
        )

        result = await router.dispatch(ctx)

        assert result is not None
        assert result.content == 'Unknown command "/neaw". Did you mean "/new"?'
        assert result.metadata["render_as"] == "text"

    @pytest.mark.asyncio
    async def test_exact_command_with_arguments_suggests_valid_form(
        self, router: CommandRouter, fake_loop: MagicMock, fake_msg: MagicMock,
    ) -> None:
        fake_msg.content = "/status now"
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="test:chat1", raw="/status now", loop=fake_loop,
        )

        result = await router.dispatch(ctx)

        assert result is not None
        assert result.content == (
            'Command "/status" does not accept arguments. Did you mean "/status"?'
        )

    @pytest.mark.asyncio
    async def test_unknown_command_without_close_match_points_to_help(
        self, router: CommandRouter, fake_loop: MagicMock, fake_msg: MagicMock,
    ) -> None:
        fake_msg.content = "/totally-unknown-command"
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="test:chat1", raw="/totally-unknown-command", loop=fake_loop,
        )

        result = await router.dispatch(ctx)

        assert result is not None
        assert result.content == (
            'Unknown command "/totally-unknown-command". '
            'Use "/help" to list available commands.'
        )


class TestPairingCommandDispatch:
    """Verify /pairing works via CommandRouter."""

    @pytest.fixture()
    def router(self) -> CommandRouter:
        r = CommandRouter()
        register_builtin_commands(r)
        return r

    @pytest.fixture()
    def fake_msg(self) -> MagicMock:
        msg = MagicMock()
        msg.channel = "telegram"
        msg.chat_id = "chat1"
        msg.content = "/pairing list"
        msg.metadata = {}
        return msg

    @pytest.mark.asyncio
    async def test_pairing_list_dispatched(
        self, router: CommandRouter, fake_msg: MagicMock, monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "nanobot.pairing.store.list_pending",
            lambda: [
                {
                    "code": "ABCD-EFGH",
                    "channel": "telegram",
                    "sender_id": "123",
                    "expires_at": 9999999999,
                }
            ],
        )
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="telegram:chat1", raw="/pairing list", args="list", loop=MagicMock(),
        )
        result = await router.dispatch(ctx)
        assert result is not None
        assert "ABCD-EFGH" in result.content
        assert result.metadata.get("_pairing_command") is True

    @pytest.mark.asyncio
    async def test_pairing_approve_dispatched(
        self, router: CommandRouter, fake_msg: MagicMock, monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "nanobot.pairing.store.approve_code",
            lambda code: ("telegram", "123") if code == "ABCD-EFGH" else None,
        )
        fake_msg.content = "/pairing approve ABCD-EFGH"
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="telegram:chat1", raw="/pairing approve ABCD-EFGH",
            args="approve ABCD-EFGH", loop=MagicMock(),
        )
        result = await router.dispatch(ctx)
        assert result is not None
        assert "Approved" in result.content
        assert result.content == (
            "Approved pairing code `ABCD-EFGH` — 123 can now access telegram"
        )
        assert result.metadata.get("_pairing_command") is True

    @pytest.mark.asyncio
    async def test_pairing_revoke_dispatched(
        self, router: CommandRouter, fake_msg: MagicMock, monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "nanobot.pairing.store.revoke",
            lambda ch, sid: sid == "123",
        )
        fake_msg.content = "/pairing revoke 123"
        ctx = CommandContext(
            msg=fake_msg, session=None,
            key="telegram:chat1", raw="/pairing revoke 123",
            args="revoke 123", loop=MagicMock(),
        )
        result = await router.dispatch(ctx)
        assert result is not None
        assert "Revoked" in result.content
        assert result.content == "Revoked 123 from telegram"
        assert result.metadata.get("_pairing_command") is True
