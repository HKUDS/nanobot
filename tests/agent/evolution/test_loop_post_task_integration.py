"""Integration tests for PostTask wiring in AgentLoop (E1 Step 4)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.evolution.models import ToolCallRecord, TurnTrace
from nanobot.agent.evolution.post_task import (
    SKIP_SUBAGENT,
    PostTaskDecision,
    PostTaskEvolver,
    PostTaskGateResult,
)
from nanobot.agent.evolution.proposals import PostTaskCreateResult
from nanobot.agent.loop import AgentLoop, TurnContext, TurnState
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import EvolutionConfig, EvolutionPostTaskConfig


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


def _trace(*, tool_call_count: int = 5, session_key: str = "cli:direct") -> TurnTrace:
    tool_calls = tuple(
        ToolCallRecord(name=f"tool_{index}", args_summary=f"arg{index}", ok=True)
        for index in range(tool_call_count)
    )
    return TurnTrace(
        session_key=session_key,
        query="deploy nginx to k8s",
        tool_calls=tool_calls,
        tool_call_count=tool_call_count,
        iterations=2,
        stop_reason="completed",
        outcome="success",
    )


def test_schedule_post_task_skips_when_evolution_disabled(tmp_path) -> None:
    loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=False))
    loop._schedule_background = MagicMock()

    loop._schedule_post_task(_trace(), is_subagent=False)

    loop._schedule_background.assert_not_called()


def test_schedule_post_task_schedules_background_when_enabled(tmp_path) -> None:
    loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
    loop._schedule_background = MagicMock()
    trace = _trace()

    loop._schedule_post_task(trace, is_subagent=False)

    loop._schedule_background.assert_called_once()
    scheduled = loop._schedule_background.call_args[0][0]
    assert asyncio.iscoroutine(scheduled)
    scheduled.close()


def test_run_post_task_skips_when_gate_fails(tmp_path) -> None:
    async def _run() -> None:
        loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
        evolver = MagicMock(spec=PostTaskEvolver)
        evolver.evaluate_gate.return_value = PostTaskGateResult.skip(SKIP_SUBAGENT)
        evolver.decide = AsyncMock()
        loop._post_task_evolver = evolver

        await loop._run_post_task(_trace(), is_subagent=True)

        evolver.decide.assert_not_awaited()

    asyncio.run(_run())


def test_run_post_task_full_pipeline_marks_cooldown(tmp_path) -> None:
    async def _run() -> None:
        loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
        evolver = MagicMock(spec=PostTaskEvolver)
        evolver.evaluate_gate.return_value = PostTaskGateResult.allow()
        evolver.decide = AsyncMock(
            return_value=PostTaskDecision(
                action="create_skill",
                skill_name="k8s-deploy",
                rationale="repeatable",
                confidence=0.9,
            )
        )
        evolver.create_proposal = AsyncMock(
            return_value=PostTaskCreateResult.ok(
                skill_name="k8s-deploy",
                skill_path="skills/.proposals/uuid/SKILL.md",
                proposal_id="uuid",
            )
        )
        evolver.cooldown_store = MagicMock()
        loop._post_task_evolver = evolver
        loop.context.warm_skill_index = MagicMock()

        trace = _trace()
        await loop._run_post_task(trace, is_subagent=False)

        evolver.create_proposal.assert_awaited_once()
        evolver.cooldown_store.mark.assert_called_once_with(trace.session_key)
        loop.context.warm_skill_index.assert_not_called()

    asyncio.run(_run())


def test_run_post_task_warms_index_on_auto_apply(tmp_path) -> None:
    async def _run() -> None:
        loop = _make_loop(
            tmp_path,
            evolution=EvolutionConfig(
                enable=True,
                post_task=EvolutionPostTaskConfig(auto_apply=True),
            ),
        )
        evolver = MagicMock(spec=PostTaskEvolver)
        evolver.evaluate_gate.return_value = PostTaskGateResult.allow()
        evolver.decide = AsyncMock(
            return_value=PostTaskDecision(
                action="create_skill",
                skill_name="k8s-deploy",
                rationale="repeatable",
                confidence=0.9,
            )
        )
        evolver.create_proposal = AsyncMock(
            return_value=PostTaskCreateResult.ok(
                skill_name="k8s-deploy",
                skill_path="skills/k8s-deploy/SKILL.md",
                auto_applied=True,
            )
        )
        evolver.cooldown_store = MagicMock()
        loop._post_task_evolver = evolver
        loop.context.warm_skill_index = MagicMock()

        await loop._run_post_task(_trace(), is_subagent=False)

        loop.context.warm_skill_index.assert_called_once()

    asyncio.run(_run())


def test_state_save_schedules_post_task(tmp_path) -> None:
    async def _run() -> None:
        loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
        loop._schedule_post_task = MagicMock()
        loop._last_usage = {"prompt": 10, "completion": 5}

        ctx = TurnContext(
            msg=InboundMessage(
                channel="cli",
                chat_id="direct",
                sender_id="user",
                content="deploy",
            ),
            session=loop.sessions.get_or_create("cli:direct"),
            session_key="cli:direct",
            state=TurnState.SAVE,
            turn_id="cli:direct:1",
            retrieval_query="deploy",
            skill_entry_names=["cron"],
            trace_baseline_len=1,
            history=[],
            final_content="done",
            tools_used=["exec"] * 5,
            all_messages=[
                {"role": "user", "content": "deploy"},
                *[
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": f"c{index}",
                                "type": "function",
                                "function": {
                                    "name": "exec",
                                    "arguments": {"command": f"cmd{index}"},
                                },
                            }
                        ],
                    }
                    for index in range(5)
                ],
                *[
                    {"role": "tool", "tool_call_id": f"c{index}", "name": "exec", "content": "ok"}
                    for index in range(5)
                ],
                {"role": "assistant", "content": "done"},
            ],
            stop_reason="completed",
        )

        await loop._state_save(ctx)

        loop._schedule_post_task.assert_called_once()
        scheduled_trace = loop._schedule_post_task.call_args[0][0]
        assert scheduled_trace.session_key == "cli:direct"
        assert loop._schedule_post_task.call_args.kwargs["is_subagent"] is False

    asyncio.run(_run())


def test_process_system_message_schedules_post_task_for_subagent_trace(tmp_path) -> None:
    async def _run() -> None:
        loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
        loop.auto_compact.prepare_session = MagicMock(
            side_effect=lambda session, key: (session, None),
        )
        loop.consolidator.maybe_consolidate_by_tokens = AsyncMock()
        loop.context.build_messages = MagicMock(return_value=[{"role": "user", "content": "task"}])
        loop._run_agent_loop = AsyncMock(
            return_value=("done", ["exec"], [{"role": "assistant", "content": "done"}], "completed", False),
        )
        loop._save_turn = MagicMock()
        loop._schedule_post_task = MagicMock()

        msg = InboundMessage(
            channel="system",
            chat_id="cli:direct",
            content="background result",
            sender_id="subagent",
        )

        await loop._process_system_message(msg)

        loop._schedule_post_task.assert_called_once()
        assert loop._schedule_post_task.call_args.kwargs["is_subagent"] is True

    asyncio.run(_run())


def test_real_evolver_gate_blocks_subagent_without_decide(tmp_path) -> None:
    async def _run() -> None:
        loop = _make_loop(tmp_path, evolution=EvolutionConfig(enable=True))
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock()
        loop._post_task_evolver = PostTaskEvolver(tmp_path, loop._evolution, provider=provider)

        await loop._run_post_task(_trace(), is_subagent=True)

        provider.chat_with_retry.assert_not_awaited()

    asyncio.run(_run())
