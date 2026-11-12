"""Runner-owned tool progress rules, without session or channel setup."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.runner_helpers import make_run_spec
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import AgentRunner
from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMResponse, ToolCallRequest
from nanobot.utils.progress_events import output_events

_DEFAULTS = AgentDefaults()


@pytest.mark.asyncio
async def test_start_and_finish_events_emitted() -> None:
    provider = MagicMock()
    tools = MagicMock()
    tool_call = ToolCallRequest(id="call1", name="custom_tool", arguments={"path": "foo.txt"})
    calls = iter([
        LLMResponse(content="Visible", tool_calls=[tool_call]),
        LLMResponse(content="Done", tool_calls=[]),
    ])
    provider.chat_stream_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
    tools.get_definitions.return_value = []
    tools.prepare_call.return_value = (None, {"path": "foo.txt"}, None)
    tools.execute = AsyncMock(return_value="ok")

    progress: list[tuple[str, bool, list[dict] | None]] = []

    async def on_progress(
        content: str,
        *,
        tool_hint: bool = False,
        tool_events: list[dict] | None = None,
    ) -> None:
        progress.append((content, tool_hint, tool_events))

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=_DEFAULTS.max_tool_iterations,
        max_tool_result_chars=_DEFAULTS.max_tool_result_chars,
        concurrent_tools=True,
        hook=AgentProgressHook(output_events(on_progress=on_progress)),
    ))

    assert result.final_content == "Done"
    assert progress == [
        ("Visible", False, None),
        (
            'custom_tool("foo.txt")',
            True,
            [{
                "version": 1,
                "phase": "start",
                "call_id": "call1",
                "name": "custom_tool",
                "arguments": {"path": "foo.txt"},
                "result": None,
                "error": None,
                "files": [],
                "embeds": [],
            }],
        ),
        (
            "",
            False,
            [{
                "version": 1,
                "phase": "end",
                "call_id": "call1",
                "name": "custom_tool",
                "arguments": {"path": "foo.txt"},
                "result": "ok",
                "error": None,
                "files": [],
                "embeds": [],
            }],
        ),
    ]


@pytest.mark.asyncio
async def test_streamed_content_is_not_repeated_before_tool_execution() -> None:
    """If content was already streamed, tool setup should not repeat it."""
    provider = MagicMock()
    tools = MagicMock()
    tool_call = ToolCallRequest(id="call1", name="custom_tool", arguments={"path": "foo.txt"})
    calls = iter([
        LLMResponse(content="I will inspect it.", tool_calls=[tool_call]),
        LLMResponse(content="Done", tool_calls=[]),
    ])

    async def chat_stream_with_retry(*, on_content_delta, **kwargs):
        response = next(calls)
        if response.tool_calls:
            await on_content_delta("I will ")
            await on_content_delta("inspect it.")
        return response

    provider.chat_stream_with_retry = chat_stream_with_retry
    provider.chat_with_retry = AsyncMock()
    tools.get_definitions.return_value = []
    tools.prepare_call.return_value = (None, {"path": "foo.txt"}, None)
    tools.execute = AsyncMock(return_value="ok")

    streamed: list[str] = []
    progress: list[tuple[str, bool, list[dict] | None]] = []

    async def on_stream(delta: str) -> None:
        streamed.append(delta)

    async def on_progress(
        content: str,
        *,
        tool_hint: bool = False,
        tool_events: list[dict] | None = None,
    ) -> None:
        progress.append((content, tool_hint, tool_events))

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[],
        tools=tools,
        model="test-model",
        max_iterations=_DEFAULTS.max_tool_iterations,
        max_tool_result_chars=_DEFAULTS.max_tool_result_chars,
        concurrent_tools=True,
        hook=AgentProgressHook(
            output_events(on_progress=on_progress, on_stream=on_stream),
            streaming=True,
        ),
    ))

    assert result.final_content == "Done"
    assert streamed == ["I will", " inspect it."]
    assert progress[0][0] == 'custom_tool("foo.txt")'
    assert all(item[0] != "I will inspect it." for item in progress)
