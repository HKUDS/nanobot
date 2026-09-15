"""File-read deduplication follows the model request, including context rewrites."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.context import TranscriptInput
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.context import current_tool_call_context
from nanobot.agent.tools.file_state import FileStates, bind_file_states, reset_file_states
from nanobot.agent.tools.filesystem import ReadFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


def _tools(tmp_path):
    (tmp_path / "data.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    tools = ToolRegistry()
    tools.register(ReadFileTool(workspace=tmp_path))
    return tools


async def _read(tools, call_id, history=None, **kwargs):
    provider = MagicMock(spec=LLMProvider)
    requests = []

    async def request(*, messages, **_kwargs):
        requests.append(deepcopy(messages))
        if len(requests) == 1:
            return LLMResponse(content=None, tool_calls=[
                ToolCallRequest(id=call_id, name="read_file", arguments={"path": "data.txt"}),
            ])
        return LLMResponse(content="done")

    provider.chat_stream_with_retry = request
    initial = None if "transcript_input" in kwargs else [
        *(history or []), {"role": "user", "content": "Read data.txt again."},
    ]
    result = await AgentRunner().run(make_run_spec(
        provider, model="test-model", tools=tools, initial_messages=initial,
        max_iterations=2, max_tool_result_chars=128_000, **kwargs,
    ))
    observation = next(
        message["content"] for message in result.messages
        if message.get("role") == "tool" and message.get("tool_call_id") == call_id
    )
    return result, observation, requests


@pytest.mark.parametrize("retained", ["original", "summary", "truncated", "stub_only", "orphan"])
async def test_repeat_requires_original_read_result_in_current_context(tmp_path, retained):
    tools = _tools(tmp_path)
    first, contents, _ = await _read(tools, "read-1")
    second, stub, _ = await _read(tools, "read-2", first.messages)
    assert "1| alpha" in contents
    assert stub == "[File unchanged since last read: data.txt]"

    history = deepcopy(second.messages)
    if retained == "summary":
        history = [{"role": "user", "content": "Summary: data.txt contains alpha and beta."}]
    elif retained == "truncated":
        for message in history:
            if message.get("tool_call_id") == "read-1":
                message["content"] = "1| alpha\n[truncated]"
    elif retained in {"stub_only", "orphan"}:
        history = [
            message for message in history
            if not any(call["id"] == "read-1" for call in message.get("tool_calls", []))
            and (retained == "orphan" or message.get("tool_call_id") != "read-1")
        ]

    _, repeated, _ = await _read(tools, "read-3", history)
    assert repeated == (stub if retained == "original" else contents)


@pytest.mark.parametrize("rewrite", ["compact", "snip"])
async def test_dedup_uses_governed_request_instead_of_raw_transcript(tmp_path, monkeypatch, rewrite):
    tools = _tools(tmp_path)
    first, contents, _ = await _read(tools, "read-1")

    def estimate(_provider, _model, messages, _tools):
        contains_original = any(message.get("tool_call_id") == "read-1" for message in messages)
        return (600 if contains_original else 100), "test-counter"

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", estimate)
    monkeypatch.setattr("nanobot.agent.context_governance.estimate_message_tokens", lambda _: 300)
    consolidate = AsyncMock(return_value="The file was inspected; its original text was omitted.")

    def build(transcript):
        system = transcript.session_summary["text"] if transcript.session_summary else "system"
        messages = [{"role": "system", "content": system}, *transcript.history]
        if transcript.current_message is not None:
            messages.append({"role": "user", "content": transcript.current_message})
        return messages

    options = {}
    if rewrite == "compact":
        options = {
            "transcript_input": TranscriptInput(
                history=first.messages, current_message="Read data.txt again.",
            ),
            "transcript_builder": build,
            "consolidate_history": consolidate,
        }
    result, repeated, requests = await _read(
        tools, "read-2", first.messages, context_window_tokens=1_624, max_tokens=100, **options,
    )

    assert any(message.get("tool_call_id") == "read-1" for message in result.messages)
    assert not any(message.get("tool_call_id") == "read-1" for message in requests[0])
    assert repeated == contents
    if rewrite == "compact":
        consolidate.assert_awaited_once()
        assert result.summary_checkpoint is not None


async def test_direct_read_without_model_context_never_omits_contents(tmp_path):
    tools = _tools(tmp_path)
    first = await tools.execute("read_file", {"path": "data.txt"})
    second = await tools.execute("read_file", {"path": "data.txt"})
    assert second == first
    assert "1| alpha" in second


async def test_native_compaction_invalidates_old_results_but_new_reads_can_dedup(tmp_path):
    tools = _tools(tmp_path)
    provider = MagicMock(spec=LLMProvider)
    requests = []

    async def request(*, messages, **_kwargs):
        requests.append(deepcopy(messages))
        if len(requests) <= 3:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(
                    id=f"read-{len(requests)}", name="read_file", arguments={"path": "data.txt"},
                )],
                provider_compaction_applied=len(requests) == 2,
                provider_compaction_scope="current_request" if len(requests) == 2 else None,
            )
        return LLMResponse(content="done")

    provider.chat_stream_with_retry = request
    result = await AgentRunner().run(make_run_spec(
        provider, model="test-model", tools=tools,
        initial_messages=[{"role": "user", "content": "Read data.txt."}],
        max_iterations=4, max_tool_result_chars=128_000,
    ))
    observations = [message["content"] for message in result.messages if message.get("role") == "tool"]
    assert "1| alpha" in observations[0]
    assert observations[1] == observations[0]
    assert observations[2] == "[File unchanged since last read: data.txt]"
    assert any(message.get("tool_call_id") == "read-1" for message in requests[2])


async def test_concurrent_sessions_keep_separate_read_contexts(tmp_path, monkeypatch):
    tools = _tools(tmp_path)
    session_a, session_b = FileStates(), FileStates()

    async def session_read(states, call_id, history=None):
        token = bind_file_states(states)
        try:
            return await _read(tools, call_id, history)
        finally:
            reset_file_states(token)

    first, contents, _ = await session_read(session_a, "read-a1")
    tool = tools.get("read_file")
    execute = tool.execute

    async def interleave(**kwargs):
        await asyncio.sleep(0)
        return await execute(**kwargs)

    monkeypatch.setattr(tool, "execute", interleave)
    (_, repeated, _), (_, other_session, _) = await asyncio.gather(
        session_read(session_a, "read-a2", first.messages),
        session_read(session_b, "read-b1"),
    )
    assert repeated == "[File unchanged since last read: data.txt]"
    assert other_session == contents
    assert current_tool_call_context() is None
