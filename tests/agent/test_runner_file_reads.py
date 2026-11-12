"""File-read deduplication follows the model request, including context rewrites."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.context import TranscriptInput
from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.execution import execute_tool_calls
from nanobot.agent.tools.file_state import FileStates, bind_file_states, reset_file_states
from nanobot.agent.tools.filesystem import ListDirTool, ReadFileTool
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


async def test_dedup_uses_compacted_request_instead_of_raw_transcript(tmp_path, monkeypatch):
    tools = _tools(tmp_path)
    first, contents, _ = await _read(tools, "read-1")

    def estimate(_provider, _model, messages, _tools):
        contains_original = any(message.get("tool_call_id") == "read-1" for message in messages)
        return (600 if contains_original else 100), "test-counter"

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", estimate)
    consolidate = AsyncMock(return_value="The file was inspected; its original text was omitted.")

    def build(transcript):
        system = transcript.session_summary["text"] if transcript.session_summary else "system"
        messages = [{"role": "system", "content": system}, *transcript.history]
        if transcript.current_message is not None:
            messages.append({"role": "user", "content": transcript.current_message})
        return messages

    result, repeated, requests = await _read(
        tools,
        "read-2",
        first.messages,
        context_window_tokens=1_624,
        max_tokens=100,
        transcript_input=TranscriptInput(
            history=first.messages, current_message="Read data.txt again.",
        ),
        transcript_builder=build,
        consolidate_history=consolidate,
    )

    assert any(message.get("tool_call_id") == "read-1" for message in result.messages)
    assert not any(message.get("tool_call_id") == "read-1" for message in requests[0])
    assert repeated == contents
    consolidate.assert_awaited_once()
    assert result.summary_checkpoint is not None


async def test_direct_read_without_model_context_never_omits_contents(tmp_path):
    tools = _tools(tmp_path)
    first = await tools.execute("read_file", {"path": "data.txt"})
    second = await tools.execute("read_file", {"path": "data.txt"})
    assert second == first
    assert "1| alpha" in second


@pytest.mark.parametrize("operation", ["list_dir", "first_read", "forced_read", "repeat_batch"])
async def test_only_repeat_reads_scan_model_results_once_per_batch(tmp_path, operation):
    tools = _tools(tmp_path)
    tools.register(ListDirTool(workspace=tmp_path))
    first, contents, _ = await _read(tools, "read-1")

    class CountedMessages(list):
        scans = 0

        def __iter__(self):
            self.scans += 1
            return super().__iter__()

    messages = CountedMessages(first.messages)
    name, arguments = "read_file", {"path": "data.txt"}
    if operation == "list_dir":
        name, arguments = "list_dir", {"path": "."}
    elif operation == "first_read":
        (tmp_path / "fresh.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        arguments = {"path": "fresh.txt"}
    elif operation == "forced_read":
        arguments["force"] = True
    calls = [ToolCallRequest(id="batch-1", name=name, arguments=arguments)]
    if operation == "repeat_batch":
        calls.append(ToolCallRequest(id="batch-2", name=name, arguments=arguments))

    results, _ = await execute_tool_calls(
        tools, calls, concurrent=True, external_lookup_counts={}, workspace_violation_counts={},
        hook=AgentHook(), context=AgentHookContext(iteration=0, messages=[]),
        model_messages=messages,
    )

    if operation == "repeat_batch":
        assert results == ["[File unchanged since last read: data.txt]"] * 2
        assert messages.scans == 1
    else:
        assert messages.scans == 0
        if operation == "list_dir":
            assert "data.txt" in results[0]
        else:
            assert results == [contents]
    # A later direct read has no model input proving that its contents are visible.
    assert await tools.execute("read_file", {"path": "data.txt"}) == contents


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_failed_file_read_restores_context(tmp_path, monkeypatch, error):
    tools = _tools(tmp_path)
    first, contents, _ = await _read(tools, "read-1")
    tool = tools.get("read_file")
    original_execute = tool.execute

    async def fail(**_kwargs):
        raise error("read interrupted")

    monkeypatch.setattr(tool, "execute", fail)
    request = execute_tool_calls(
        tools, [ToolCallRequest(id="failed-read", name="read_file", arguments={"path": "data.txt"})],
        concurrent=False, external_lookup_counts={}, workspace_violation_counts={},
        hook=AgentHook(), context=AgentHookContext(iteration=0, messages=[]),
        model_messages=first.messages,
    )
    if error is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await request
    else:
        results, _ = await request
        assert results[0].startswith("Error: RuntimeError: read interrupted")

    monkeypatch.setattr(tool, "execute", original_execute)
    assert await tools.execute("read_file", {"path": "data.txt"}) == contents


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
