import asyncio

import pytest

from nanobot.events import EventSink


async def test_prompt_scopes_isolate_parallel_runs_and_cleanup_after_cancel(tmp_path):
    from unittest.mock import MagicMock

    from agent.runner_helpers import make_run_spec
    from nanobot.agent.hook import AgentHook, CompositeHook
    from nanobot.agent.runner import AgentRunner
    from nanobot.context_sources import PromptSourcesEvent, capture_sources, record_source
    from nanobot.providers.base import LLMResponse
    from nanobot.webui.context_source_hook import ContextSourceHook

    entered = asyncio.Event()
    events = []

    async def publish(event):
        if isinstance(event, PromptSourcesEvent):
            events.append(event)

    async def run(name, blocked=False):
        class BuildPrompt(AgentHook):
            async def before_iteration(self, context):
                await asyncio.to_thread(record_source, tmp_path / name, name)

        async def provider_call(**kwargs):
            if blocked:
                entered.set()
                await asyncio.Event().wait()
            return LLMResponse(content="done")

        provider = MagicMock()
        provider.chat_stream_with_retry = provider_call
        tools = MagicMock()
        tools.get_definitions.return_value = []
        with capture_sources() as enclosing:
            hook = CompositeHook([ContextSourceHook(EventSink(publish)), BuildPrompt()])
            try:
                await AgentRunner().run(make_run_spec(
                    provider, initial_messages=[{"role": "user", "content": name}],
                    tools=tools, hook=hook, model="test", max_iterations=2, max_tool_result_chars=10000,
                ))
            finally:
                record_source(tmp_path / "after.md", "after")
                assert [source.path.name for source in enclosing.sources] == ["after.md"]

    cancelled = asyncio.create_task(run("first.md", blocked=True))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await run("second.md")
    finally:
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
    assert [[source.path.name for source in event.sources] for event in events] == [["first.md"], ["second.md"]]


async def test_compaction_publishes_rebuilt_sources_and_success_before_cancellation(tmp_path, monkeypatch):
    from functools import partial
    from unittest.mock import AsyncMock, MagicMock

    from agent.runner_helpers import make_run_spec
    from nanobot.agent.context import ContextBuilder, TranscriptInput
    from nanobot.agent.runner import AgentRunner
    from nanobot.context_sources import PromptSourcesEvent
    from nanobot.events import ContextCompactionEvent
    from nanobot.providers.base import LLMProvider
    from nanobot.webui.context_source_hook import ContextSourceHook

    (tmp_path / "SOUL.md").write_text("Be precise.", encoding="utf-8")
    entered = asyncio.Event()
    release = asyncio.Event()
    events = []

    async def publish(event):
        if isinstance(event, PromptSourcesEvent):
            events.append("sources")
            entered.set()
            await release.wait()
        elif isinstance(event, ContextCompactionEvent):
            events.append(event.phase)

    provider = MagicMock(spec=LLMProvider)
    provider.can_resume_conversation_state.return_value = False
    provider.supports_pre_request_compaction.return_value = False
    provider.chat_stream_with_retry = AsyncMock()
    tools = MagicMock()
    tools.get_definitions.return_value = []

    def estimate(_provider, _model, messages, _tools):
        return (600 if any("previous work" in str(message.get("content", "")) for message in messages) else 100, "test-counter")

    monkeypatch.setattr("nanobot.agent.context_governance.estimate_prompt_tokens_chain", estimate)

    async def run():
        sink = EventSink(publish)
        return await AgentRunner().run(make_run_spec(
            provider, initial_messages=None, tools=tools, model="test", max_iterations=1,
            max_tool_result_chars=10000, context_window_tokens=1624, max_tokens=100,
            transcript_input=TranscriptInput(history=[{"role": "user", "content": "previous work"}], current_message="hello"),
            transcript_builder=partial(ContextBuilder(tmp_path).build_transcript, channel="websocket"),
            consolidate_history=AsyncMock(return_value="summary"), hook=ContextSourceHook(sink), events=sink,
        ))

    task = asyncio.create_task(run())
    ready = asyncio.create_task(entered.wait())
    try:
        done, _ = await asyncio.wait((ready, task), return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task
            pytest.fail("compaction did not publish prompt sources")
        task.cancel()
    finally:
        release.set()
        ready.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert events == ["started", "sources", "succeeded"]
    provider.chat_stream_with_retry.assert_not_awaited()
