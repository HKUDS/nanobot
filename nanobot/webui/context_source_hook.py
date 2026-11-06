"""Turn-scoped prompt observation installed by WebUI runtime composition."""
from __future__ import annotations

from nanobot.agent.hook import AgentHook, AgentRunHookContext, AgentTurnHookContext
from nanobot.context_sources import PromptSourcesEvent, capture_sources
from nanobot.events import EventSink


class ContextSourceHook(AgentHook):
    def __init__(self, events: EventSink) -> None:
        super().__init__()
        self._events = events
        self._capture = capture_sources()
        self._sources = self._capture.__enter__()

    def has_run_hooks(self) -> bool:
        # Cleanup owns no transcript; avoid copying all messages for this observer.
        return False

    async def before_model_request(self) -> None:
        sources = tuple(self._sources)
        self._sources.clear()
        if sources:
            await self._events.emit(PromptSourcesEvent(sources))

    async def on_finally(self, context: AgentRunHookContext) -> None:
        self._sources.clear()
        self._capture.__exit__(None, None, None)


def create_context_source_hook(context: AgentTurnHookContext) -> AgentHook | None:
    return ContextSourceHook(context.events) if context.events.accepts(PromptSourcesEvent) else None
