"""Integration tests for TraceRecorder wiring in AgentLoop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.loop import AgentLoop, TurnContext, TurnState
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import EvolutionConfig


def _make_loop(tmp_path, *, evolution: EvolutionConfig | None = None) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        evolution=evolution or EvolutionConfig(),
    )


def test_agent_loop_initializes_trace_recorder(tmp_path) -> None:
    loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))

    assert loop._evolution.enable is True
    assert loop._trace_recorder.store.db_path.parent.name == ".nanobot"


def test_record_turn_trace_skips_when_disabled(tmp_path) -> None:
    loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=False))

    loop._record_turn_trace(
        session_key="cli:direct",
        query="hello",
        messages=[{"role": "assistant", "content": "hi"}],
        stop_reason="completed",
    )

    assert loop._trace_recorder.store.count() == 0


def test_record_turn_trace_persists_when_enabled(tmp_path) -> None:
    loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
    loop._last_usage = {"prompt": 50, "completion": 10}

    loop._record_turn_trace(
        session_key="cli:direct",
        query="deploy cron",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "exec", "arguments": {"command": "crontab -l"}},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ],
        stop_reason="completed",
        skills_injected=["cron"],
        tools_used=["exec"],
        turn_id="turn-1",
        baseline_len=1,
    )

    assert loop._trace_recorder.store.count() == 1
    trace = loop._trace_recorder.store.list_by_session("cli:direct")[0]
    assert trace.query == "deploy cron"
    assert trace.skills_injected == ("cron",)
    assert trace.tool_call_count == 1
    assert trace.turn_id == "turn-1"
    assert trace.token_usage_dict == {"prompt": 50, "completion": 10}


def test_state_save_records_trace(tmp_path) -> None:
    async def _run() -> None:
        loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
        loop._last_usage = {"prompt": 100, "completion": 20}

        ctx = TurnContext(
            msg=InboundMessage(
                channel="cli",
                chat_id="direct",
                sender_id="user",
                content="list files",
            ),
            session=loop.sessions.get_or_create("cli:direct"),
            session_key="cli:direct",
            state=TurnState.SAVE,
            turn_id="cli:direct:123",
            retrieval_query="list files",
            skill_entry_names=["cron"],
            trace_baseline_len=2,
            history=[{"role": "user", "content": "old"}],
            final_content="done",
            tools_used=["exec"],
            all_messages=[
                {"role": "user", "content": "list files"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "exec", "arguments": {"command": "ls"}},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "c1", "name": "exec", "content": "ok"},
                {"role": "assistant", "content": "done"},
            ],
            stop_reason="completed",
        )

        await loop._state_save(ctx)

        assert loop._trace_recorder.store.count() == 1
        stored = loop._trace_recorder.store.list_by_session("cli:direct")[0]
        assert stored.query == "list files"
        assert stored.skills_injected == ("cron",)
        assert stored.turn_id == "cli:direct:123"

    asyncio.run(_run())


def test_process_system_message_records_trace(tmp_path) -> None:
    async def _run() -> None:
        loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
        loop.auto_compact.prepare_session = MagicMock(
            side_effect=lambda session, key: (session, None),
        )
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
        loop.context.build_messages = MagicMock(return_value=[{"role": "user", "content": "task"}])
        loop._run_agent_loop = AsyncMock(
            return_value=(
                "done",
                ["exec"],
                [
                    {"role": "user", "content": "task"},
                    {"role": "assistant", "content": "done"},
                ],
                "completed",
                False,
            ),
        )
        loop._save_turn = MagicMock()

        msg = InboundMessage(
            channel="system",
            chat_id="cli:direct",
            content="background result",
            sender_id="subagent",
        )

        await loop._process_system_message(msg)

        assert loop._trace_recorder.store.count() == 1
        trace = loop._trace_recorder.store.list_recent(limit=1)[0]
        assert trace.session_key == "cli:direct"
        assert trace.stop_reason == "completed"

    asyncio.run(_run())
