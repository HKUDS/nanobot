"""Inline reasoning should not change when a provider splits its stream."""

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.events import AgentEvent, EventSink


@pytest.mark.parametrize("chunks, expected", [
    (["<think>first paragraph</think><thought>second paragraph</thought>"],
     "first paragraph\n\nsecond paragraph"),
    (["<think>first paragraph</think>", "<thought>second paragraph</thought>"],
     "first paragraph\n\nsecond paragraph"),
    (["<think>first paragraph</think><think></think><thought>second paragraph</thought>"],
     "first paragraph\n\n\n\nsecond paragraph"),
    (["<think>first paragraph</think>", "<think></think>", "<thought>second paragraph</thought>"],
     "first paragraph\n\n\n\nsecond paragraph"),
])
async def test_inline_reasoning_preserves_paragraph_separators(chunks: list[str], expected: str) -> None:
    events: list[AgentEvent] = []

    async def publish(event: AgentEvent) -> None:
        events.append(event)

    hook = AgentProgressHook(EventSink(publish=publish), streaming=True)
    context = AgentHookContext(iteration=0, messages=[])

    for chunk in chunks:
        await hook.on_stream(context, chunk)

    reasoning = "".join(
        event.content for event in events
        if isinstance(event, ProgressEvent) and event.reasoning_delta
    )
    assert reasoning == expected
    assert context.streamed_reasoning is True
