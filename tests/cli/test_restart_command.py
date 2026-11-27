from __future__ import annotations

import asyncio
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent.session_helpers import make_agent_loop

from nanobot.agent.context import TranscriptInput
from nanobot.bus.events import InboundMessage
from nanobot.command.results import message_text
from nanobot.providers.base import GenerationSettings, LLMResponse, LLMUsage
from nanobot.session.manager import Session
from nanobot.session.state import SessionState


def _make_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock(aclose=AsyncMock(), generation=GenerationSettings())
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    sessions = MagicMock()
    with patch("nanobot.agent.loop.SubagentManager") as mock_sub_mgr:
        sessions.state = MagicMock(spec=SessionState)
        sessions.state.get = AsyncMock(side_effect=lambda key: Session(key))
        sessions.state.peek.return_value = None
        sessions.state.project_history = AsyncMock(return_value=None)
        mock_sub_mgr.return_value.close = AsyncMock()
        mock_sub_mgr.return_value.get_running_count_by_session.return_value = 0
        loop = make_agent_loop(
            bus=bus, provider=provider, workspace=workspace,
            context_builder=MagicMock(workspace=workspace), session_manager=sessions,
        )
    return loop, bus


class TestRestartCommand:

    @pytest.mark.asyncio
    async def test_restart_sends_message_and_calls_execv(self):
        from nanobot.command.builtin import cmd_restart
        from nanobot.command.router import CommandContext
        from nanobot.utils.restart import (
            RESTART_NOTIFY_CHANNEL_ENV,
            RESTART_NOTIFY_CHAT_ID_ENV,
            RESTART_STARTED_AT_ENV,
        )

        loop, _bus = _make_loop()
        loop.restart_mode = "exec"
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/restart")
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/restart", loop=loop)

        with patch.dict(os.environ, {}, clear=False), \
             patch("nanobot.command.builtin.os.execv") as mock_execv:
            out = await cmd_restart(ctx)
            assert "Restarting" in message_text(out)
            mock_execv.assert_not_called()
            out.confirm_sent()
            await asyncio.sleep(0)
            assert os.environ.get(RESTART_NOTIFY_CHANNEL_ENV) == "cli"
            assert os.environ.get(RESTART_NOTIFY_CHAT_ID_ENV) == "direct"
            assert os.environ.get(RESTART_STARTED_AT_ENV)

            mock_execv.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_windows_auto_spawns_and_exits(self):
        from nanobot.command.builtin import cmd_restart
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/restart")
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/restart", loop=loop)

        with patch.dict(os.environ), \
             patch("nanobot.command.builtin.sys.platform", "win32"), \
             patch("nanobot.command.builtin.subprocess.CREATE_NEW_PROCESS_GROUP", 512, create=True), \
             patch("nanobot.command.builtin.subprocess.Popen") as mock_popen, \
             patch("nanobot.command.builtin.os._exit") as mock_exit, \
             patch("nanobot.command.builtin.os.execv") as mock_execv:
            (await cmd_restart(ctx)).confirm_sent()
            await asyncio.sleep(0)

        mock_popen.assert_called_once_with(
            [sys.executable, "-m", "nanobot"] + sys.argv[1:],
            creationflags=512,
        )
        mock_exit.assert_called_once_with(0)
        mock_execv.assert_not_called()

    @pytest.mark.asyncio
    async def test_restart_exit_mode_does_not_spawn(self):
        from nanobot.command.builtin import cmd_restart
        from nanobot.command.router import CommandContext

        loop, _bus = _make_loop()
        loop.restart_mode = "exit"
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/restart")
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/restart", loop=loop)

        with patch.dict(os.environ), \
             patch("nanobot.command.builtin.subprocess.Popen") as mock_popen, \
             patch("nanobot.command.builtin.os._exit") as mock_exit, \
             patch("nanobot.command.builtin.os.execv") as mock_execv:
            (await cmd_restart(ctx)).confirm_sent()
            await asyncio.sleep(0)

        mock_exit.assert_called_once_with(0)
        mock_popen.assert_not_called()
        mock_execv.assert_not_called()

    @pytest.mark.asyncio
    async def test_restart_intercepted_in_run_loop(self):
        loop, bus = _make_loop()
        loop.restart_mode = "exec"
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/restart")

        from nanobot.channels.manager import ChannelManager

        with patch.object(loop, "_enqueue_session_message", new_callable=MagicMock) as mock_dispatch, \
             patch.dict(os.environ), patch("nanobot.command.builtin.os.execv") as mock_execv:
            await bus.publish_inbound(msg)

            loop._running = True
            run_task = asyncio.create_task(loop.run())
            out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
            loop._running = False
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

            mock_dispatch.assert_not_called()
            assert "Restarting" in message_text(out)
            mock_execv.assert_not_called()
            channel = AsyncMock()
            channel.send_command_result.return_value = None
            await ChannelManager._send_once(channel, out)
            channel.send_command_result.assert_awaited_once_with(out)
            await asyncio.sleep(0)
            mock_execv.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", ["disconnected", "cancelled", "failed"])
    async def test_unconfirmed_restart_falls_back_once(self, monkeypatch, failure):
        from nanobot.command.builtin import cmd_restart
        from nanobot.command.router import CommandContext

        loop, _ = _make_loop()
        loop.restart_mode = "exec"
        msg = InboundMessage("telegram", "user", "chat", "/restart")
        ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw=msg.content, loop=loop)
        restarted = asyncio.Event()
        monkeypatch.setattr("nanobot.command.builtin._RESTART_ACK_TIMEOUT_S", 0.05)
        with patch.dict(os.environ), \
             patch("nanobot.command.builtin.os.execv", side_effect=lambda *_: restarted.set()) as execv:
            out = await cmd_restart(ctx)
            assert out.sent is not None
            if failure == "cancelled":
                out.sent.cancel()
            elif failure == "failed":
                out.sent.set_exception(OSError("send failed"))
            await asyncio.sleep(0)
            execv.assert_not_called()
            await asyncio.wait_for(restarted.wait(), 1)
            out.confirm_sent()  # A write can finish after the deadline.
            await asyncio.sleep(0)
            execv.assert_called_once()

    @pytest.mark.asyncio
    async def test_status_intercepted_in_run_loop(self):
        loop, bus = _make_loop()
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/status")

        with patch.object(loop, "_enqueue_session_message", new_callable=MagicMock) as mock_dispatch:
            await bus.publish_inbound(msg)

            loop._running = True
            run_task = asyncio.create_task(loop.run())
            out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
            loop._running = False
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass

            mock_dispatch.assert_not_called()
            assert "nanobot" in message_text(out).lower() or "Model" in message_text(out)

    @pytest.mark.asyncio
    async def test_run_propagates_external_cancellation(self):
        loop, _bus = _make_loop()

        run_task = asyncio.create_task(loop.run())
        await asyncio.sleep(0)
        run_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run_task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_help_includes_restart(self):
        loop, bus = _make_loop()
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/help")

        response = await loop._process_message(msg)

        assert response is not None
        assert "/restart" in message_text(response)
        assert "/status" in message_text(response)
        assert response.metadata == {}

    @pytest.mark.asyncio
    async def test_status_reports_runtime_info(self):
        loop, _bus = _make_loop()
        session = Session("telegram:c1")
        session.add_message("user", [{"type": "image_attachment", "id": "a" * 64}])
        session.add_message("assistant", "Image received")
        session.add_message("user", "Continue")
        session.metadata = {
            "_last_usage": LLMUsage.reported(input_tokens=0, output_tokens=0).to_dict()
        }
        loop.sessions.state.get = AsyncMock(return_value=session)
        loop._start_time = time.time() - 125
        loop.consolidator.estimate_session_prompt_tokens = MagicMock(
            return_value=(20500, "tiktoken")
        )
        loop.subagents.get_running_count_by_session.return_value = 0

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/status")
        runtime = loop.llm_runtime()
        loop.set_runtime_model("replacement-model")
        loop.set_runtime_context_window(10)
        loop.provider.generation = SimpleNamespace(
            temperature=1.0,
            max_tokens=1,
            reasoning_effort=None,
        )

        response = await loop._process_message(msg, runtime=runtime)

        assert response is not None
        assert "Model: test-model" in message_text(response)
        assert "Tokens: 0 in / 0 out" in message_text(response)
        assert "Context: ≈20500/200000 (≈10%)" in message_text(response)
        assert "Session: 3 messages" in message_text(response)
        assert "Uptime: 0:02:05" in message_text(response)
        assert "Tasks: 0 active" in message_text(response)
        assert response.metadata == {}
        loop.consolidator.estimate_session_prompt_tokens.assert_called_once_with(
            session,
            runtime=runtime,
        )

    @pytest.mark.asyncio
    async def test_status_counts_running_dispatch_and_subagent_tasks(self):
        loop, _bus = _make_loop()
        session = Session("telegram:c1")
        session.add_message("user", "Hello")
        loop.sessions.state.get = AsyncMock(return_value=session)
        loop.consolidator.estimate_session_prompt_tokens = MagicMock(
            return_value=(1000, "tiktoken")
        )

        running_task = MagicMock()
        running_task.done.return_value = False
        finished_task = MagicMock()
        finished_task.done.return_value = True

        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/status")
        loop._active_tasks[msg.session_key] = {running_task, finished_task}
        loop.subagents.get_running_count_by_session.return_value = 2

        response = await loop._process_message(msg)

        assert response is not None
        assert "Tasks: 3 active" in message_text(response)

    @pytest.mark.asyncio
    async def test_run_agent_loop_estimates_usage_when_provider_omits_it(self, monkeypatch):
        loop, _bus = _make_loop()
        monkeypatch.setattr(
            "nanobot.agent.runner.estimate_prompt_tokens_chain",
            lambda *_args, **_kwargs: (123, "test"),
        )
        monkeypatch.setattr(
            "nanobot.agent.runner.estimate_message_tokens",
            lambda _message: 7,
        )
        loop.provider.chat_stream_with_retry = AsyncMock(side_effect=[
            LLMResponse(content="first", usage=LLMUsage.reported(input_tokens=9, output_tokens=4)),
            LLMResponse(content="second", usage=None),
        ])

        first = await loop._run_agent_loop(
            TranscriptInput(history=[], current_message=None),
            runtime=loop.llm_runtime(),
        )
        assert first.usage == LLMUsage.reported(input_tokens=9, output_tokens=4)

        second = await loop._run_agent_loop(
            TranscriptInput(history=[], current_message=None),
            runtime=loop.llm_runtime(),
        )
        assert second.usage == LLMUsage.estimated(input_tokens=123, output_tokens=7)

    @pytest.mark.parametrize(
        "has_request_history, expected", [
            (True, "Context (last request): 80000/204800 (39%)"),
            (False, "Context: unavailable (last recorded request: 80000 tokens)"),
        ]
    )
    @pytest.mark.asyncio
    async def test_status_uses_request_context_after_model_switch(
        self, tmp_path, has_request_history: bool, expected: str
    ):
        from nanobot.session.display_history import HistoryFact, HistoryKind
        from nanobot.session.manager import SessionManager

        loop, _bus = _make_loop()
        loop.set_runtime_context_window(128_000)
        channel = "websocket" if has_request_history else "telegram"
        session = Session(f"{channel}:c1")
        session.add_message("user", "Hello")
        usage = LLMUsage.reported(input_tokens=82_000, output_tokens=500)
        for _ in range(16):
            usage += LLMUsage.reported(input_tokens=82_000, output_tokens=500)
        usage += LLMUsage.reported(input_tokens=80_000, output_tokens=500)
        session.metadata["_last_usage"] = usage.to_dict()
        sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
        sessions.save(session)
        if has_request_history:
            await sessions.state.append_history(session.key, [HistoryFact(HistoryKind.MODEL_REQUEST, {
                "phase": "completed", "request_usage": {"context_tokens": 80_000},
                "usage": usage.to_turn_dict(), "context_window_tokens": 204_800,
            })], expected_generation=session.generation)
        loop.sessions.state.project_history = sessions.state.project_history
        loop.sessions.state.get = AsyncMock(return_value=session)
        loop.consolidator.estimate_session_prompt_tokens = MagicMock(side_effect=RuntimeError("unavailable"))

        response = await loop._process_message(
            InboundMessage(channel=channel, sender_id="u1", chat_id="c1", content="/status")
        )

        assert response is not None
        assert "Tokens: 1474000 in / 9000 out" in message_text(response)
        assert expected in message_text(response)
        if has_request_history:
            loop.consolidator.estimate_session_prompt_tokens.assert_not_called()
        await sessions.state.aclose()

    @pytest.mark.asyncio
    async def test_process_direct_preserves_render_metadata(self):
        loop, _bus = _make_loop()
        loop.sessions.state.get = AsyncMock(return_value=Session("cli:test"))
        loop.subagents.get_running_count.return_value = 0
        loop.subagents.get_running_count_by_session.return_value = 0

        response = await loop.process_direct("/status", session_key="cli:test")

        assert response is not None
        assert "Tasks:" in response.content
        assert response.metadata["render_as"] == "text"
