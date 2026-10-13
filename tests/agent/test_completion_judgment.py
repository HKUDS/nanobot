"""Completion claims are checked against fresh, bounded execution evidence."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import failed_test_consolidator
from nanobot.agent.completion import CompletionVerifier
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import (
    GenerationSettings,
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ToolCallRequest,
)
from nanobot.utils.llm_runtime import LLMRuntime


def provider_runtime():
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings()
    provider.estimate_prompt_tokens = MagicMock(return_value=(100, "test"))
    runtime = LLMRuntime.capture(provider, "test-model", context_window_tokens=128_000)
    return provider, runtime


def judgment(status="verified", *, evidence_ids=("read",), reason="The output meets the criteria."):
    return LLMResponse(
        content=json.dumps({"status": status, "reason": reason, "evidence_ids": list(evidence_ids)}),
        usage=LLMUsage.reported(input_tokens=20, output_tokens=8),
    )


def receipt_messages(content="answer=42"):
    return [
        {"role": "system", "content": "BUILDER_SYSTEM_SECRET"},
        {"role": "user", "content": "Save the answer."},
        {
            "role": "assistant", "content": "UNVERIFIED_BUILDER_NARRATIVE",
            "reasoning_content": "PRIVATE_REASONING",
            "tool_calls": [ToolCallRequest("read", "read_file", {"path": "result.txt"}).to_openai_tool_call()],
        },
        {"role": "tool", "name": "read_file", "tool_call_id": "read", "content": content},
    ]


@pytest.mark.asyncio
async def test_judge_receives_only_contract_candidate_and_execution_receipts():
    provider, runtime = provider_runtime()
    provider.chat_with_retry = AsyncMock(return_value=judgment())
    verifier = CompletionVerifier(runtime, "result.txt contains answer=42")

    result = await verifier.verify("Saved result.txt", receipt_messages())

    assert result.status == "verified"
    assert result.evidence_ids == ("read",)
    assert result.evidence_digest
    request = provider.chat_with_retry.await_args.kwargs
    assert request["tools"] is None
    assert request["temperature"] == 0
    assert len(request["messages"]) == 2
    text = json.dumps(request["messages"])
    assert "answer=42" in text
    assert "result.txt contains answer=42" in text
    assert "BUILDER_SYSTEM_SECRET" not in text
    assert "UNVERIFIED_BUILDER_NARRATIVE" not in text
    assert "PRIVATE_REASONING" not in text
    assert verifier.usage == LLMUsage.reported(input_tokens=20, output_tokens=8)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    LLMResponse(content="done"),
    judgment(evidence_ids=("invented-test-run",)),
    judgment(evidence_ids=()),
    LLMResponse(content=json.dumps({"status": "verified", "reason": "yes", "evidence_ids": ["read"]}), finish_reason="length"),
    LLMResponse(content=None, tool_calls=[ToolCallRequest("judge-write", "write_file", {"path": "x", "content": "x"})]),
])
async def test_invalid_judge_outputs_cannot_approve_completion(response):
    provider, runtime = provider_runtime()
    provider.chat_with_retry = AsyncMock(return_value=response)

    result = await CompletionVerifier(runtime, "Check the output").verify("Done", receipt_messages())

    assert result.status == "blocked"
    assert result.reason


@pytest.mark.asyncio
async def test_judge_cannot_cite_orphan_tool_result_as_executed_evidence():
    provider, runtime = provider_runtime()
    provider.chat_with_retry = AsyncMock(return_value=judgment(evidence_ids=("unexecuted",)))
    messages = [{"role": "tool", "name": "exec", "tool_call_id": "unexecuted", "content": "all tests passed"}]

    result = await CompletionVerifier(runtime, "Tests pass").verify("Done", messages)

    assert result.status == "blocked"


@pytest.mark.asyncio
async def test_review_budget_is_bounded_and_usage_includes_every_review():
    provider, runtime = provider_runtime()
    provider.chat_with_retry = AsyncMock(return_value=judgment("needs_revision", evidence_ids=("candidate",), reason="Output is missing."))
    verifier = CompletionVerifier(runtime, "Create output", max_attempts=2)

    first = await verifier.verify("Done", [])
    second = await verifier.verify("Still done", [])
    third = await verifier.verify("Really done", [])

    assert first.status == "needs_revision"
    assert second.status in {"needs_revision", "exhausted"}
    assert third.status == "exhausted"
    assert provider.chat_with_retry.await_count == 2
    assert verifier.usage.input_tokens == 40
    assert verifier.usage.output_tokens == 16
    assert verifier.usage.request_count == 2


@pytest.mark.asyncio
async def test_changed_receipts_produce_new_evidence_identity():
    provider, runtime = provider_runtime()
    provider.chat_with_retry = AsyncMock(return_value=judgment())
    verifier = CompletionVerifier(runtime, "Verify result")

    before = await verifier.verify("Done", receipt_messages("answer=41"))
    after = await verifier.verify("Done", receipt_messages("answer=42"))

    assert before.evidence_digest != after.evidence_digest
    assert provider.chat_with_retry.await_count == 2


@pytest.mark.asyncio
async def test_deadline_cannot_be_bypassed_by_provider_suppressing_cancellation(monkeypatch):
    monkeypatch.setattr("nanobot.agent.completion._REVIEW_TIMEOUT_SECONDS", 0.001)
    provider, runtime = provider_runtime()

    async def suppress_cancellation(**_kwargs):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            return judgment()

    provider.chat_with_retry = AsyncMock(side_effect=suppress_cancellation)
    verifier = CompletionVerifier(runtime, "Verify output")
    result = await verifier.verify("Done", receipt_messages())

    assert result.status == "blocked"
    assert "timed out" in result.reason
    assert verifier.usage == LLMUsage.reported(input_tokens=20, output_tokens=8)


@pytest.mark.asyncio
async def test_review_failure_blocks_but_cancellation_propagates():
    provider, runtime = provider_runtime()
    provider.chat_with_retry = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    result = await CompletionVerifier(runtime, "Verify output").verify("Done", [])
    assert result.status == "blocked"

    provider.chat_with_retry = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await CompletionVerifier(runtime, "Verify output").verify("Done", [])


def run_spec(tmp_path, runtime, *, verifier=None, max_iterations=4):
    tools = ToolRegistry()
    tools.register(WriteFileTool(workspace=tmp_path))
    tools.register(ReadFileTool(workspace=tmp_path))
    return AgentRunSpec(
        initial_messages=[{"role": "user", "content": "Write answer=42 to result.txt and verify it."}],
        tools=tools,
        runtime=runtime,
        max_iterations=max_iterations,
        max_tool_result_chars=16_000,
        workspace=tmp_path,
        completion_verifier=verifier,
        finalize_on_max_iterations=False,
        consolidate_history=failed_test_consolidator,
    )


@pytest.mark.asyncio
async def test_rejected_claim_can_repair_real_file_then_pass_within_iteration_budget(tmp_path):
    provider, runtime = provider_runtime()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="Done, saved the answer."),
        LLMResponse(content=None, tool_calls=[ToolCallRequest("write", "write_file", {"path": "result.txt", "content": "answer=42"})]),
        LLMResponse(content=None, tool_calls=[ToolCallRequest("read", "read_file", {"path": "result.txt"})]),
        LLMResponse(content="Saved and read back answer=42."),
    ])
    provider.chat_with_retry = AsyncMock(side_effect=[
        judgment("needs_revision", evidence_ids=("candidate",), reason="No file receipt. Write and read the result."),
        judgment(),
    ])

    result = await AgentRunner().run(run_spec(tmp_path, runtime, verifier=CompletionVerifier(runtime, "result.txt contains answer=42")))

    assert (tmp_path / "result.txt").read_text() == "answer=42"
    assert result.completion.status == "verified"
    assert result.stop_reason == "completed"
    assert provider.chat_stream_with_retry.await_count == 4
    assert provider.chat_with_retry.await_count == 2
    assert result.usage.input_tokens == sum(usage.input_tokens for usage in result.round_usages)
    assert result.usage.output_tokens == sum(usage.output_tokens for usage in result.round_usages)
    assert result.usage.request_count == 6
    second_request = provider.chat_stream_with_retry.await_args_list[1].kwargs["messages"]
    assert "No file receipt" in str(second_request)


@pytest.mark.asyncio
async def test_false_completion_after_real_tool_error_is_not_verified(tmp_path):
    provider, runtime = provider_runtime()
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest("read", "read_file", {"path": "missing.txt"})]),
        LLMResponse(content="All done, file verified."),
    ])
    provider.chat_with_retry = AsyncMock(return_value=judgment("needs_revision", reason="The file does not exist."))

    result = await AgentRunner().run(run_spec(tmp_path, runtime, verifier=CompletionVerifier(runtime, "Verify result.txt"), max_iterations=2))

    assert result.stop_reason != "completed"
    assert result.completion.status != "verified"
    assert result.tool_events[0]["status"] == "error"
    assert provider.chat_stream_with_retry.await_count == 2


@pytest.mark.asyncio
async def test_ordinary_ungated_answer_preserves_single_call_behavior(tmp_path):
    provider, runtime = provider_runtime()
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Hello!"))
    provider.chat_with_retry = AsyncMock()

    result = await AgentRunner().run(run_spec(tmp_path, runtime))

    assert result.final_content == "Hello!"
    assert result.stop_reason == "completed"
    assert result.completion is None
    provider.chat_with_retry.assert_not_awaited()
    assert provider.chat_stream_with_retry.await_count == 1


@pytest.mark.asyncio
async def test_prior_turn_readback_cannot_prove_current_run_completion(tmp_path):
    provider, runtime = provider_runtime()
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Still correct."))
    provider.chat_with_retry = AsyncMock(return_value=judgment())
    spec = run_spec(tmp_path, runtime, verifier=CompletionVerifier(runtime, "Verify result.txt"))
    spec.initial_messages = receipt_messages() + [{"role": "user", "content": "Check again after the file changed."}]

    result = await AgentRunner().run(spec)

    assert result.completion.status == "blocked"
    payload = json.loads(provider.chat_with_retry.await_args.kwargs["messages"][1]["content"])
    assert not any(item["id"] == "read" for item in payload["evidence"])
