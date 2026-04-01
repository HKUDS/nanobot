"""OTelHook: records metrics and traces for tool executions and skill activations."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext

if TYPE_CHECKING:
    from opentelemetry.trace import Span


class OTelHook(AgentHook):
    """AgentHook that records OTEL metrics and traces for each iteration.

    - One span per agent iteration.
    - Counter + histogram per tool call.
    - Counter for skill activations.
    - All OTEL calls wrapped in try/except to never crash the agent.
    """

    def __init__(self, channel: str = "unknown", chat_id: str = "unknown") -> None:
        from nanobot.observability.otel import get_meter, get_tracer

        self._channel = channel
        self._chat_id = chat_id
        self._current_span: Span | None = None
        self._tool_start_times: dict[str, float] = {}
        self._tools_in_session: set[str] = set()

        meter = get_meter()
        tracer = get_tracer()

        self._tool_calls_counter = (
            meter.create_counter(
                "nanobot.tool.calls",
                description="Number of tool invocations",
            )
            if meter
            else None
        )

        self._tool_duration = (
            meter.create_histogram(
                "nanobot.tool.duration",
                description="Tool execution duration in ms",
                unit="ms",
            )
            if meter
            else None
        )

        self._skill_counter = (
            meter.create_counter(
                "nanobot.skill.loaded",
                description="Number of times a skill is activated",
            )
            if meter
            else None
        )

        self._active_tools_histogram = (
            meter.create_histogram(
                "nanobot.session.active_tools",
                description="Distinct tools used per session",
            )
            if meter
            else None
        )

        self._iteration_counter = (
            meter.create_counter(
                "nanobot.agent.iterations",
                description="Agent loop iterations",
            )
            if meter
            else None
        )

        self._tracer = tracer

    async def before_iteration(self, context: AgentHookContext) -> None:
        try:
            if self._tracer:
                self._current_span = self._tracer.start_span(
                    "agent.iteration",
                    attributes={
                        "channel": self._channel,
                        "chat_id": self._chat_id,
                        "iteration": context.iteration,
                    },
                )
                self._current_span.__enter__()
        except Exception:
            logger.debug("OTEL: failed to start iteration span")

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        now = time.monotonic()
        for tc in context.tool_calls:
            self._tool_start_times[tc.id] = now

    async def after_iteration(self, context: AgentHookContext) -> None:
        now = time.monotonic()

        for event in context.tool_events:
            try:
                attrs = {
                    "tool_name": event.get("name", "unknown"),
                    "status": event.get("status", "unknown"),
                    "channel": self._channel,
                }
                if self._tool_calls_counter:
                    self._tool_calls_counter.add(1, attributes=attrs)

                tool_name = event.get("name", "")
                self._tools_in_session.add(tool_name)

                start = self._tool_start_times.get(tool_name, now)
                duration_ms = (now - start) * 1000
                if self._tool_duration and start != now:
                    self._tool_duration.record(duration_ms, attributes={"tool_name": tool_name})
            except Exception:
                logger.debug("OTEL: failed to record tool metric")

        try:
            if self._active_tools_histogram and self._tools_in_session:
                self._active_tools_histogram.record(
                    len(self._tools_in_session),
                    attributes={"channel": self._channel},
                )
        except Exception:
            logger.debug("OTEL: failed to record active tools")

        try:
            if self._iteration_counter:
                self._iteration_counter.add(
                    1,
                    attributes={
                        "channel": self._channel,
                        "stop_reason": context.stop_reason or "unknown",
                    },
                )
        except Exception:
            logger.debug("OTEL: failed to record iteration")

        try:
            if self._current_span:
                self._current_span.__exit__(None, None, None)
                self._current_span = None
        except Exception:
            logger.debug("OTEL: failed to end iteration span")

        self._tool_start_times.clear()

    def record_skill(self, skill_name: str) -> None:
        """Record a skill activation event."""
        try:
            if self._skill_counter:
                self._skill_counter.add(
                    1,
                    attributes={"skill_name": skill_name, "channel": self._channel},
                )
        except Exception:
            logger.debug("OTEL: failed to record skill metric")
