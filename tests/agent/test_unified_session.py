import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.session_helpers import mock_session_manager, run_session
from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.file_state import FileStateStore
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.builtin import cmd_new, register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.config.schema import AgentDefaults, Config
from nanobot.session.keys import UNIFIED_SESSION_KEY
from nanobot.session.manager import SessionManager


def _make_loop(tmp_path: Path, unified_session: bool = False) -> AgentLoop:
    """Create a minimal AgentLoop for dispatch-level tests."""
    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    with patch("nanobot.agent.loop.SessionManager", side_effect=mock_session_manager), \
         patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr:
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            unified_session=unified_session,
        )
    return loop


def _make_msg(channel: str = "telegram", chat_id: str = "111",
              session_key_override: str | None = None) -> InboundMessage:
    return InboundMessage(
        channel=channel,
        chat_id=chat_id,
        sender_id="user1",
        content="hello",
        session_key_override=session_key_override,
    )


class TestUnifiedSessionDispatch:

    @pytest.mark.asyncio
    async def test_unified_session_rewrites_key_to_unified_default(self, tmp_path: Path):
        loop = _make_loop(tmp_path, unified_session=True)

        captured: list[str] = []

        async def fake_process(msg, **kwargs):
            captured.append(msg.session_key)
            return None

        loop._process_message = fake_process  # type: ignore[method-assign]

        msg = _make_msg(channel="telegram", chat_id="111")
        await run_session(loop, msg)

        assert captured == ["unified:default"]

    @pytest.mark.asyncio
    async def test_unified_session_different_channels_share_same_key(self, tmp_path: Path):
        loop = _make_loop(tmp_path, unified_session=True)

        captured: list[str] = []

        async def fake_process(msg, **kwargs):
            captured.append(msg.session_key)
            return None

        loop._process_message = fake_process  # type: ignore[method-assign]

        await run_session(loop, _make_msg(channel="telegram", chat_id="111"))
        await run_session(loop, _make_msg(channel="discord", chat_id="222"))
        await run_session(loop, _make_msg(channel="cli", chat_id="direct"))

        assert captured == ["unified:default", "unified:default", "unified:default"]

    @pytest.mark.asyncio
    async def test_unified_session_disabled_preserves_original_key(self, tmp_path: Path):
        loop = _make_loop(tmp_path, unified_session=False)

        captured: list[str] = []

        async def fake_process(msg, **kwargs):
            captured.append(msg.session_key)
            return None

        loop._process_message = fake_process  # type: ignore[method-assign]

        msg = _make_msg(channel="telegram", chat_id="999")
        await run_session(loop, msg)

        assert captured == ["telegram:999"]

    @pytest.mark.asyncio
    async def test_unified_session_respects_existing_override(self, tmp_path: Path):
        loop = _make_loop(tmp_path, unified_session=True)

        captured: list[str] = []

        async def fake_process(msg, **kwargs):
            captured.append(msg.session_key)
            return None

        loop._process_message = fake_process  # type: ignore[method-assign]

        msg = _make_msg(channel="telegram", chat_id="111", session_key_override="telegram:thread:42")
        await run_session(loop, msg)

        assert captured == ["telegram:thread:42"]

    def test_unified_session_default_is_false(self, tmp_path: Path):
        loop = _make_loop(tmp_path)
        assert loop._unified_session is False


class TestUnifiedSessionConfig:

    def test_agent_defaults_unified_session_default_is_false(self):
        defaults = AgentDefaults()
        assert defaults.unified_session is False

    def test_agent_defaults_unified_session_can_be_enabled(self):
        defaults = AgentDefaults(unified_session=True)
        assert defaults.unified_session is True

    def test_config_serialises_unified_session_as_camel_case(self):
        config = Config()
        data = config.model_dump(mode="json", by_alias=True)
        agents_defaults = data["agents"]["defaults"]
        assert "unifiedSession" in agents_defaults
        assert agents_defaults["unifiedSession"] is False

    def test_config_parses_unified_session_from_camel_case(self):
        raw = {"agents": {"defaults": {"unifiedSession": True}}}
        config = Config.model_validate(raw)
        assert config.agents.defaults.unified_session is True

    def test_config_parses_unified_session_from_snake_case(self):
        raw = {"agents": {"defaults": {"unified_session": True}}}
        config = Config.model_validate(raw)
        assert config.agents.defaults.unified_session is True

    def test_onboard_generated_config_contains_unified_session(self, tmp_path: Path):
        from nanobot.config.loader import save_config

        config = Config()
        config_path = tmp_path / "config.json"
        save_config(config, config_path)

        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)

        agents_defaults = data["agents"]["defaults"]
        assert "unifiedSession" in agents_defaults, (
            "onboard-generated config.json must contain 'unifiedSession' key"
        )
        assert agents_defaults["unifiedSession"] is False


class TestCmdNewUnifiedSession:

    def test_new_is_not_a_priority_command(self):
        router = CommandRouter()
        register_builtin_commands(router)
        assert router.is_priority("/new") is False

    def test_new_is_an_exact_command(self):
        router = CommandRouter()
        register_builtin_commands(router)
        assert "/new" in router._exact

    @pytest.mark.asyncio
    async def test_cmd_new_clears_unified_session(self, tmp_path: Path):
        sessions = SessionManager(tmp_path)

        shared = sessions.get_or_create("unified:default")
        shared.add_message("user", "hello from telegram")
        shared.add_message("assistant", "hi there")
        sessions.save(shared)
        assert len(sessions.get_or_create("unified:default").messages) == 2
        expected_snapshot = list(shared.messages)

        # schedule_background is a *sync* method that schedules a coroutine via
        # asyncio.create_task().  Mirror that exactly so the coroutine is consumed
        # and no RuntimeWarning is emitted.
        admitted_runtime = MagicMock(name="admitted_runtime")
        file_state_store = FileStateStore()
        previous_file_state = file_state_store.for_session("unified:default")
        tracked_file = tmp_path / "tracked.txt"
        tracked_file.write_text("tracked", encoding="utf-8")
        previous_file_state.record_read(tracked_file)
        loop = SimpleNamespace(
            sessions=sessions,
            consolidator=SimpleNamespace(archive_session=AsyncMock(return_value=True)),
            _cancel_active_tasks=AsyncMock(return_value=0),
            discard_session_file_state=file_state_store.discard,
            llm_runtime=MagicMock(return_value=MagicMock()),
            schedule_background=lambda coro: asyncio.ensure_future(coro),
        )

        msg = InboundMessage(
            channel="telegram", sender_id="user1", chat_id="111", content="/new",
            session_key_override="unified:default",
        )
        ctx = CommandContext(
            msg=msg,
            session=None,
            key="unified:default",
            raw="/new",
            loop=loop,
            runtime=admitted_runtime,
        )

        result = await cmd_new(ctx)

        assert "New session started" in result.content
        sessions.invalidate("unified:default")
        reloaded = sessions.get_or_create("unified:default")
        assert reloaded.messages == []
        reset_file_state = file_state_store.for_session("unified:default")
        assert reset_file_state is not previous_file_state
        assert reset_file_state.is_unchanged(tracked_file) is False
        archived = loop.consolidator.archive_session.call_args.args[0]
        assert archived.key == "unified:default"
        assert archived.messages == expected_snapshot
        assert archived.last_archived == 0
        loop.consolidator.archive_session.assert_called_once_with(
            archived,
            archive_end=len(expected_snapshot),
            runtime=admitted_runtime,
        )
        loop.llm_runtime.assert_not_called()

    @pytest.mark.asyncio
    async def test_cmd_new_in_unified_mode_does_not_affect_other_sessions(self, tmp_path: Path):
        sessions = SessionManager(tmp_path)

        other = sessions.get_or_create("discord:999")
        other.add_message("user", "discord message")
        sessions.save(other)

        shared = sessions.get_or_create("unified:default")
        shared.add_message("user", "shared message")
        sessions.save(shared)

        loop = SimpleNamespace(
            sessions=sessions,
            consolidator=SimpleNamespace(archive_session=AsyncMock(return_value=True)),
            _cancel_active_tasks=AsyncMock(return_value=0),
            discard_session_file_state=MagicMock(),
            runtime_for_session=AsyncMock(return_value=MagicMock()),
            schedule_background=lambda coro: asyncio.ensure_future(coro),
        )

        msg = InboundMessage(
            channel="telegram", sender_id="user1", chat_id="111", content="/new",
            session_key_override="unified:default",
        )
        ctx = CommandContext(msg=msg, session=None, key="unified:default", raw="/new", loop=loop)
        await cmd_new(ctx)

        sessions.invalidate("unified:default")
        sessions.invalidate("discord:999")
        assert sessions.get_or_create("unified:default").messages == []
        assert len(sessions.get_or_create("discord:999").messages) == 1


class TestStopCommandWithUnifiedSession:

    @pytest.mark.asyncio
    async def test_active_tasks_use_effective_key_in_unified_mode(self, tmp_path: Path):
        loop = _make_loop(tmp_path, unified_session=True)

        msg = _make_msg(channel="telegram", chat_id="123456")

        loop._process_message = AsyncMock(return_value=None)
        (await loop._enqueue_session_message(msg))
        assert set(loop._active_tasks) == {UNIFIED_SESSION_KEY}
        await asyncio.gather(*loop._active_tasks[UNIFIED_SESSION_KEY])

    @pytest.mark.asyncio
    async def test_stop_command_finds_task_in_unified_mode(self, tmp_path: Path):
        from nanobot.command.builtin import cmd_stop

        loop = _make_loop(tmp_path, unified_session=True)

        async def long_running():
            await asyncio.sleep(10)

        task = asyncio.create_task(long_running())
        loop._active_tasks[UNIFIED_SESSION_KEY] = {task}

        msg = InboundMessage(
            channel="telegram",
            chat_id="123456",
            sender_id="user1",
            content="/stop",
            session_key_override=UNIFIED_SESSION_KEY,
        )

        ctx = CommandContext(msg=msg, session=None, key=UNIFIED_SESSION_KEY, raw="/stop", loop=loop)

        result = await cmd_stop(ctx)

        assert task.cancelled() or task.done()
        assert "Stopped 1 task" in result.content

    @pytest.mark.asyncio
    async def test_stop_command_uses_effective_key_without_session_override(self, tmp_path: Path):
        from nanobot.command.builtin import cmd_stop

        loop = _make_loop(tmp_path, unified_session=True)

        async def long_running():
            await asyncio.sleep(10)

        task = asyncio.create_task(long_running())
        loop._active_tasks[UNIFIED_SESSION_KEY] = {task}
        msg = InboundMessage(
            channel="telegram",
            chat_id="123456",
            sender_id="user1",
            content="/stop",
        )
        ctx = CommandContext(msg=msg, session=None, key=UNIFIED_SESSION_KEY, raw="/stop", loop=loop)

        result = await cmd_stop(ctx)

        assert task.cancelled() or task.done()
        assert "Stopped 1 task" in result.content

    @pytest.mark.asyncio
    async def test_stop_command_cross_channel_in_unified_mode(self, tmp_path: Path):
        from nanobot.command.builtin import cmd_stop

        loop = _make_loop(tmp_path, unified_session=True)

        async def long_running():
            await asyncio.sleep(10)

        task1 = asyncio.create_task(long_running())
        task2 = asyncio.create_task(long_running())
        loop._active_tasks[UNIFIED_SESSION_KEY] = {task1, task2}

        msg = InboundMessage(
            channel="discord",
            chat_id="789012",
            sender_id="user2",
            content="/stop",
            session_key_override=UNIFIED_SESSION_KEY,
        )

        ctx = CommandContext(msg=msg, session=None, key=UNIFIED_SESSION_KEY, raw="/stop", loop=loop)

        result = await cmd_stop(ctx)

        assert "Stopped 2 task" in result.content
