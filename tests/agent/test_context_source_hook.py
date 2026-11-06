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
                assert [source.path.name for source in enclosing] == ["after.md"]

    cancelled = asyncio.create_task(run("first.md", blocked=True))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await run("second.md")
    finally:
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
    assert [[source.path.name for source in event.sources] for event in events] == [["first.md"], ["second.md"]]
