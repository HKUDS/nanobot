"""Runtime state facts and turn-scoped publication through MessageBus."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nanobot.bus.events import InboundMessage
from nanobot.events import AgentEvent
from nanobot.providers.base import LLMUsage

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.utils.llm_runtime import LLMRuntime


@dataclass(frozen=True)
class RuntimeEventContext:
    """Routing context common to turn-scoped runtime events."""

    channel: str
    chat_id: str
    session_key: str
    metadata: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionTurnStarted(AgentEvent):
    """A user/system turn has loaded its session and is about to build context."""

    context: RuntimeEventContext


@dataclass(frozen=True)
class UserInputAccepted(AgentEvent):
    """User input was accepted for dispatch or injection into a session."""

    context: RuntimeEventContext
    content: str


@dataclass(frozen=True)
class TurnRuntimeAdmitted(AgentEvent):
    """The immutable model runtime selected for one admitted turn."""

    context: RuntimeEventContext
    runtime: LLMRuntime


@dataclass(frozen=True)
class TurnRunStatusChanged(AgentEvent):
    """Visible run status changed for a turn."""

    context: RuntimeEventContext
    status: str
    started_at: float | None = None


@dataclass(frozen=True)
class TurnCompleted(AgentEvent):
    """A turn has delivered its final user-visible response."""

    context: RuntimeEventContext
    latency_ms: int | None = None
    runtime: LLMRuntime | None = None
    usage: LLMUsage | None = None
    # Logical model rounds in display order; recovery dispatches are aggregated.
    round_usages: tuple[LLMUsage, ...] = ()
    outcome: str = "completed"
    failure_kind: str | None = None
    failure_error_kind: str | None = None
    failure_attempts: int | None = None


@dataclass(frozen=True)
class SessionTurnPersisted(AgentEvent):
    """A completed turn has been written to local session storage."""

    context: RuntimeEventContext
    turn_id: str
    sender_id: str


@dataclass(frozen=True)
class GoalStateChanged(AgentEvent):
    """A session's sustained-goal state changed."""

    context: RuntimeEventContext
    session_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeModelChanged(AgentEvent):
    """The active runtime model/preset changed."""

    model: str
    model_preset: str | None


class RuntimeEventPublisher:
    """Convenience publisher for turn-scoped runtime events.

    Agent code should decide when state transitions happen; this helper owns
    the mechanics of building event contexts and carrying per-turn metadata.
    """

    def __init__(self, bus: MessageBus) -> None:
        self.bus = bus
        self._turn_latency_ms: dict[str, int] = {}
        self._turn_runtime: dict[str, LLMRuntime] = {}
        self._turn_usage: dict[str, LLMUsage] = {}
        self._turn_round_usages: dict[str, tuple[LLMUsage, ...]] = {}

    @staticmethod
    def _context(
        *,
        channel: str,
        chat_id: str,
        session_key: str,
        metadata: dict[str, Any] | None,
        attributes: dict[str, Any] | None = None,
    ) -> RuntimeEventContext:
        return RuntimeEventContext(
            channel=channel,
            chat_id=chat_id,
            session_key=session_key,
            metadata=dict(metadata or {}),
            attributes=dict(attributes or {}),
        )

    def record_turn_runtime(self, session_key: str, runtime: LLMRuntime) -> None:
        self._turn_runtime[session_key] = runtime

    def record_turn_latency(self, session_key: str, latency_ms: int | None) -> None:
        if latency_ms is not None:
            self._turn_latency_ms[session_key] = int(latency_ms)

    def record_turn_usage(
        self,
        session_key: str,
        round_usages: list[LLMUsage],
    ) -> None:
        if not round_usages:
            return

        usage = round_usages[0]
        for round_usage in round_usages[1:]:
            usage += round_usage
        previous = self._turn_usage.get(session_key)
        self._turn_usage[session_key] = usage if previous is None else previous + usage
        self._turn_round_usages[session_key] = (
            *self._turn_round_usages.get(session_key, ()),
            *round_usages,
        )

    def clear_turn(self, session_key: str) -> None:
        self._turn_latency_ms.pop(session_key, None)
        self._turn_runtime.pop(session_key, None)
        self._turn_usage.pop(session_key, None)
        self._turn_round_usages.pop(session_key, None)

    async def user_input_accepted(
        self,
        msg: InboundMessage,
        session_key: str,
    ) -> None:
        await self.bus.publish(
            UserInputAccepted(
                context=self._context(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    session_key=session_key,
                    metadata=msg.metadata,
                ),
                content=msg.content,
            )
        )

    async def session_turn_started(
        self,
        msg: InboundMessage,
        session_key: str,
    ) -> None:
        await self.bus.publish(
            SessionTurnStarted(
                context=self._context(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    session_key=session_key,
                    metadata=msg.metadata,
                ),
            )
        )

    async def turn_runtime_admitted(
        self,
        msg: InboundMessage,
        session_key: str,
        runtime: LLMRuntime,
    ) -> None:
        """Record and publish the runtime selected for one turn."""
        self.record_turn_runtime(session_key, runtime)
        await self.bus.publish(
            TurnRuntimeAdmitted(
                context=self._context(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    session_key=session_key,
                    metadata=msg.metadata,
                ),
                runtime=runtime,
            )
        )

    async def run_status_changed(
        self,
        msg: InboundMessage,
        session_key: str,
        status: str,
        *,
        started_at: float | None = None,
    ) -> None:
        await self.bus.publish(
            TurnRunStatusChanged(
                context=self._context(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    session_key=session_key,
                    metadata=msg.metadata,
                ),
                status=status,
                started_at=started_at,
            )
        )

    async def session_turn_persisted(
        self,
        msg: InboundMessage,
        session_key: str,
        *,
        turn_id: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        await self.bus.publish(
            SessionTurnPersisted(
                context=self._context(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    session_key=session_key,
                    metadata=msg.metadata,
                    attributes=attributes,
                ),
                turn_id=turn_id,
                sender_id=msg.sender_id,
            )
        )

    async def turn_completed(
        self,
        *,
        channel: str,
        chat_id: str,
        session_key: str,
        metadata: dict[str, Any] | None,
        outcome: str = "completed",
        failure_kind: str | None = None,
        failure_error_kind: str | None = None,
        failure_attempts: int | None = None,
    ) -> None:
        await self.bus.publish(
            TurnCompleted(
                context=self._context(
                    channel=channel,
                    chat_id=chat_id,
                    session_key=session_key,
                    metadata=metadata,
                ),
                latency_ms=self._turn_latency_ms.pop(session_key, None),
                runtime=self._turn_runtime.pop(session_key, None),
                usage=self._turn_usage.pop(session_key, None),
                round_usages=self._turn_round_usages.pop(session_key, ()),
                outcome=outcome,
                failure_kind=failure_kind,
                failure_error_kind=failure_error_kind,
                failure_attempts=failure_attempts,
            )
        )

    def runtime_model_changed(self, model: str, model_preset: str | None) -> None:
        self.bus.publish_nowait(
            RuntimeModelChanged(model=model, model_preset=model_preset)
        )
