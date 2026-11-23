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
    session_generation: str | None = None


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
class SubagentTaskChanged(AgentEvent):
    """A parent-owned task observation changed."""

    context: RuntimeEventContext
    task_id: str


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
        self._turn_latency_ms: dict[tuple[str, str | None], int] = {}
        self._turn_runtime: dict[tuple[str, str | None], LLMRuntime] = {}
        self._turn_usage: dict[tuple[str, str | None], LLMUsage] = {}
        self._turn_round_usages: dict[tuple[str, str | None], tuple[LLMUsage, ...]] = {}

    @staticmethod
    def _context(
        *,
        channel: str,
        chat_id: str,
        session_key: str,
        metadata: dict[str, Any] | None,
        attributes: dict[str, Any] | None = None,
        session_generation: str | None = None,
    ) -> RuntimeEventContext:
        return RuntimeEventContext(
            channel=channel,
            chat_id=chat_id,
            session_key=session_key,
            session_generation=session_generation,
            metadata=dict(metadata or {}),
            attributes=dict(attributes or {}),
        )

    def record_turn_runtime(
        self, session_key: str, runtime: LLMRuntime, *, run_id: str | None = None,
    ) -> None:
        self._turn_runtime[(session_key, run_id)] = runtime

    def record_turn_latency(
        self, session_key: str, latency_ms: int | None, *, run_id: str | None = None,
    ) -> None:
        if latency_ms is not None:
            self._turn_latency_ms[(session_key, run_id)] = int(latency_ms)

    def record_turn_usage(
        self,
        session_key: str,
        round_usages: list[LLMUsage],
        *, run_id: str | None = None,
    ) -> None:
        if not round_usages:
            return

        usage = round_usages[0]
        for round_usage in round_usages[1:]:
            usage += round_usage
        key = (session_key, run_id)
        self._turn_usage[key] = usage
        self._turn_round_usages[key] = tuple(round_usages)

    def clear_turn(self, session_key: str, *, run_id: str | None = None) -> None:
        key = (session_key, run_id)
        self._turn_latency_ms.pop(key, None)
        self._turn_runtime.pop(key, None)
        self._turn_usage.pop(key, None)
        self._turn_round_usages.pop(key, None)

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
                    session_generation=msg.session_generation,
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
                    session_generation=msg.session_generation,
                ),
            )
        )

    async def turn_runtime_admitted(
        self,
        msg: InboundMessage,
        session_key: str,
        runtime: LLMRuntime,
        *, run_id: str | None = None,
    ) -> None:
        """Record and publish the runtime selected for one turn."""
        self.record_turn_runtime(session_key, runtime, run_id=run_id)
        await self.bus.publish(
            TurnRuntimeAdmitted(
                context=self._context(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    session_key=session_key,
                    metadata=msg.metadata,
                    session_generation=msg.session_generation,
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
                    session_generation=msg.session_generation,
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
                    session_generation=msg.session_generation,
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
        run_id: str | None = None,
    ) -> None:
        key = (session_key, run_id)
        await self.bus.publish(
            TurnCompleted(
                context=self._context(
                    channel=channel,
                    chat_id=chat_id,
                    session_key=session_key,
                    metadata=metadata,
                ),
                latency_ms=self._turn_latency_ms.pop(key, None),
                runtime=self._turn_runtime.pop(key, None),
                usage=self._turn_usage.pop(key, None),
                round_usages=self._turn_round_usages.pop(key, ()),
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
