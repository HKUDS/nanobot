"""Child completion reviews reach parent results and durable task status."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.registry import is_tool_error_result
from nanobot.agent.tools.subagent import SubagentTool
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.session.manager import SessionManager
from nanobot.utils.llm_runtime import LLMRuntime


def setup(tmp_path, *, max_iterations=4, persist=False):
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens = MagicMock(return_value=(100, "test"))
    runtime = LLMRuntime.capture(provider, "test-model", context_window_tokens=128_000)
    manager = SubagentManager(
        workspace=tmp_path, bus=MessageBus(), max_tool_result_chars=16_000,
        consolidator=MagicMock(), max_iterations=max_iterations,
        session_manager=SessionManager(tmp_path) if persist else None,
    )
    return manager, provider, runtime


def review(status, *, evidence_ids=("read",), reason="Readback meets the criteria."):
    return LLMResponse(content=json.dumps({
        "status": status, "reason": reason, "evidence_ids": list(evidence_ids),
    }))


@pytest.mark.asyncio
async def test_verified_child_delivers_receipted_result_to_parent(tmp_path):
    manager, provider, runtime = setup(tmp_path, persist=True)
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest("write", "write_file", {"path": "result.txt", "content": "answer=42"})]),
        LLMResponse(content=None, tool_calls=[ToolCallRequest("read", "read_file", {"path": "result.txt"})]),
        LLMResponse(content="Saved and read back answer=42."),
    ])
    provider.chat_with_retry = AsyncMock(return_value=review("verified"))
    try:
        await manager.spawn(
            task="Write result.txt", runtime=runtime, origin_channel="cli", origin_chat_id="parent",
            acceptance_criteria="result.txt contains answer=42 and is read back.",
        )
        await asyncio.gather(*list(manager._running_tasks.values()))
        status = next(iter(manager.statuses_for_session("cli:parent").values()))
        notice = await asyncio.wait_for(manager.bus.consume_inbound(), timeout=1)
    finally:
        await manager.close()

    assert (tmp_path / "result.txt").read_text() == "answer=42"
    assert status.state == "done"
    assert status.completion.status == "verified"
    assert status.as_dict()["completion"]["evidence_ids"] == ["read"]
    assert notice.metadata["subagent_completion"]["status"] == "verified"
    assert "verified" in notice.content.lower()
    assert provider.chat_with_retry.await_count == 1
    restored, _provider, _runtime = setup(tmp_path, persist=True)
    try:
        restored_status = restored.check(status.task_id, "cli:parent")
        assert restored_status.completion == status.completion
        assert restored_status.acceptance_criteria == status.acceptance_criteria
        assert restored_status.state == "done"
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_two_rejected_child_claims_stay_incomplete_in_status_and_announcement(tmp_path):
    manager, provider, runtime = setup(tmp_path)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="All done."))
    provider.chat_with_retry = AsyncMock(return_value=review(
        "needs_revision", evidence_ids=("candidate",), reason="No file was produced.",
    ))
    try:
        await manager.spawn(
            task="Write result.txt", runtime=runtime, origin_channel="cli", origin_chat_id="parent",
            acceptance_criteria="result.txt exists and contains answer=42.",
        )
        await asyncio.gather(*list(manager._running_tasks.values()))
        status = next(iter(manager.statuses_for_session("cli:parent").values()))
        notice = await asyncio.wait_for(manager.bus.consume_inbound(), timeout=1)
    finally:
        await manager.close()

    assert not (tmp_path / "result.txt").exists()
    assert status.state == "incomplete"
    assert status.completion.status == "exhausted"
    assert notice.metadata["subagent_state"] == "incomplete"
    assert notice.metadata["subagent_completion"]["status"] == "exhausted"
    assert "completed successfully" not in notice.content
    assert provider.chat_with_retry.await_count == 2
    assert provider.chat_stream_with_retry.await_count <= 4


@pytest.mark.asyncio
async def test_ungated_child_finishes_without_claiming_independent_verification(tmp_path):
    manager, provider, runtime = setup(tmp_path)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="A concise answer."))
    provider.chat_with_retry = AsyncMock()
    try:
        await manager.spawn(task="Answer briefly", runtime=runtime, origin_channel="cli", origin_chat_id="parent")
        await asyncio.gather(*list(manager._running_tasks.values()))
        status = next(iter(manager.statuses_for_session("cli:parent").values()))
        notice = await asyncio.wait_for(manager.bus.consume_inbound(), timeout=1)
    finally:
        await manager.close()

    assert status.state == "done"
    assert status.completion is None
    assert "completed successfully" not in notice.content
    assert "finished" in notice.content
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["refusal", "content_filter"])
async def test_policy_stopped_child_is_never_announced_as_success(tmp_path, finish_reason):
    manager, provider, runtime = setup(tmp_path)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(
        content="Request blocked by provider policy.", finish_reason=finish_reason,
    ))
    provider.chat_with_retry = AsyncMock()
    try:
        await manager.spawn(task="Perform the task", runtime=runtime, origin_channel="cli", origin_chat_id="parent")
        await asyncio.gather(*list(manager._running_tasks.values()))
        status = next(iter(manager.statuses_for_session("cli:parent").values()))
        notice = await asyncio.wait_for(manager.bus.consume_inbound(), timeout=1)
    finally:
        await manager.close()

    assert status.state == "incomplete"
    assert status.stop_reason == finish_reason
    assert notice.metadata["subagent_state"] == "incomplete"
    assert "completed successfully" not in notice.content
    provider.chat_with_retry.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("criteria", ["", "x" * 4001])
async def test_invalid_child_criteria_rejected_before_task_is_started(tmp_path, criteria):
    manager, provider, runtime = setup(tmp_path)
    context = RequestContext("cli", "parent", session_key="cli:parent", runtime=runtime)
    try:
        with request_context(context):
            result = await SubagentTool(manager).execute(action="create", task="Write report", acceptance_criteria=criteria)
        assert is_tool_error_result(result)
        assert manager.get_running_count() == 0
        provider.chat_stream_with_retry.assert_not_called()
    finally:
        await manager.close()
