"""Deliver explicitly user-facing image results independently of model narration."""

from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.events import EventSink
from nanobot.providers.base import ToolCallRequest
from nanobot.utils.image_artifacts import (
    MAX_TURN_IMAGES,
    ImageArtifact,
    ImageArtifactResult,
    ImageArtifactsEvent,
)


class ImageArtifactsHook(AgentHook):
    def __init__(self, events: EventSink) -> None:
        super().__init__()
        self._events = events
        self._seen: set[str] = set()

    async def after_execute_tool(
        self, context: AgentHookContext, tool_call: ToolCallRequest,
        tool: Any, params: dict[str, Any], result: Any,
    ) -> None:
        if not isinstance(result, ImageArtifactResult):
            return
        images: list[ImageArtifact] = []
        for artifact in result.artifacts:
            if artifact.path in self._seen or len(self._seen) >= MAX_TURN_IMAGES:
                continue
            self._seen.add(artifact.path)
            images.append(artifact)
        if images:
            await self._events.emit(ImageArtifactsEvent(tuple(images), tool_call.id))
