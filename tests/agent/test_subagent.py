"""Tests for SubagentManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.agent.subagent import SubagentManager, SubagentStatus
from nanobot.bus.queue import MessageBus
from nanobot.llm_usage.context import llm_usage_source
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.security.workspace_access import build_workspace_scope
from nanobot.utils.llm_runtime import LLMRuntime


def _runtime(provider: LLMProvider) -> LLMRuntime:
    provider.generation = GenerationSettings()
    return LLMRuntime.capture(provider, "test", context_window_tokens=128_000)


@pytest.mark.asyncio
async def test_subagent_keeps_project_runtime_scope_with_agent_owned_tools(tmp_path):
    agent_workspace = tmp_path / "agent"
    project = tmp_path / "project"
    agent_workspace.mkdir()
    project.mkdir()
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    manager = SubagentManager(
        workspace=agent_workspace,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )
    manager._execute_session = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    manager._announce_result = AsyncMock()
    status = SubagentStatus(
        task_id="t1",
        label="label",
        task_description="task",
        started_at=0.0,
    )

    await manager._run_subagent(
        "t1",
        "task",
        "label",
        {"channel": "websocket", "chat_id": "direct"},
        status,
        _runtime(provider),
        workspace_scope=build_workspace_scope(project, "restricted"),
    )

    spec = manager._execute_session.call_args.args[0]
    assert spec.workspace_scope.project_path == project
    assert spec.tools_config.restrict_to_workspace


@pytest.mark.asyncio
async def test_subagent_recovers_from_tool_error_in_same_run(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="reading",
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="read_file",
                    arguments={"path": "missing.txt"},
                )
            ],
        ),
        LLMResponse(content="recovered without restarting", tool_calls=[]),
    ])
    sm = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
        consolidator=MagicMock(),
    )

    result = await sm.run_inline(
        task="recover after a missing file",
        session_key="test:direct",
        runtime=_runtime(provider),
    )

    assert result == "recovered without restarting"
    assert provider.chat_stream_with_retry.await_count == 2


@pytest.mark.asyncio
async def test_subagent_pressure_uses_transient_summary(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    provider.can_resume_conversation_state.return_value = False
    provider.generation = GenerationSettings(max_tokens=100)

    def estimate(messages, _tools, _model):
        if sum(message.get("role") == "tool" for message in messages) >= 2:
            return 600, "test-counter"
        return 100, "test-counter"

    provider.estimate_prompt_tokens = MagicMock(side_effect=estimate)
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="checking",
            tool_calls=[ToolCallRequest(
                id="call-1",
                name="list_dir",
                arguments={"path": "."},
            )],
        ),
        LLMResponse(
            content="checking again",
            tool_calls=[ToolCallRequest(
                id="call-2",
                name="list_dir",
                arguments={"path": "."},
            )],
        ),
        LLMResponse(content="done", tool_calls=[]),
    ])
    consolidator = MagicMock()
    consolidator.summarize_transcript = AsyncMock(return_value="Subagent checkpoint.")
    consolidator.summarize_provider_compaction = AsyncMock(return_value=None)
    manager = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
        consolidator=consolidator,
    )
    runtime = LLMRuntime.capture(
        provider,
        "test",
        context_window_tokens=1_624,
    )

    result = await manager.run_inline(
        task="inspect the workspace",
        session_key="test:direct",
        runtime=runtime,
    )

    assert result == "done"
    consolidator.summarize_transcript.assert_awaited_once()
    assert consolidator.summarize_transcript.await_args.kwargs["persist"] is False
    model_request = provider.chat_stream_with_retry.await_args_list[2].kwargs["messages"]
    assert "Subagent checkpoint." in model_request[0]["content"]
    assert sum(message.get("role") == "tool" for message in model_request) == 1


@pytest.mark.asyncio
async def test_spawned_subagent_inherits_llm_usage_source(tmp_path):
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=16_000,
    )
    sm._execute_session = AsyncMock(
        return_value=AgentRunResult(final_content="ok", messages=[], stop_reason="completed")
    )
    sm._announce_result = AsyncMock()

    with llm_usage_source("cron"):
        await sm.spawn(
            "automation task",
            session_key="websocket:bound-automation",
            runtime=_runtime(provider),
        )
    tasks = list(sm._running_tasks.values())
    await asyncio.gather(*tasks)

    spec = sm._execute_session.call_args.args[0]
    assert spec.llm_usage_source == "cron"
