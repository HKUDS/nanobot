"""Project agent runtime events onto the WebUI wire protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    GoalStateSyncEvent,
    GoalStatusEvent,
    ProgressEvent,
    RecoveryStateEvent,
    RuntimeModelUpdatedEvent,
    SessionUpdatedEvent,
    TurnEndEvent,
    TurnModelUpdatedEvent,
    UserInputEvent,
    outbound_event_from_message,
)
from nanobot.session.webui_turns import clear_websocket_turn_if_current
from nanobot.webui.metadata import (
    WEBSOCKET_TURN_OWNER_METADATA_KEY,
    WEBUI_SYSTEM_COMMAND_TURN_PREFIX,
    WEBUI_TURN_METADATA_KEY,
)
from nanobot.webui.session_identity import webui_session_key
from nanobot.webui.session_projection import WebUISessionProjection

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

    from nanobot.providers.base import LLMUsage


class WebUIOutboundTransport(Protocol):
    """Wire operations required by the outbound application projector."""

    def webui_subscribers(self, chat_id: str) -> tuple[ServerConnection, ...]: ...

    async def send_runtime_model_updated(
        self,
        *,
        model_name: str | None,
        model_preset: str | None = None,
    ) -> None: ...

    async def send_turn_model_updated(
        self,
        chat_id: str,
        *,
        model_name: str,
        model_preset: str | None = None,
        context_window_tokens: int | None = None,
        fallback: bool = False,
    ) -> None: ...

    async def send_user_input(
        self,
        chat_id: str,
        *,
        content: str,
        created_at_ms: int,
        provenance: dict[str, Any],
    ) -> None: ...

    async def send_recovery_state(self, chat_id: str, event: RecoveryStateEvent) -> None: ...

    async def send_goal_state(self, chat_id: str, blob: dict[str, Any]) -> None: ...

    async def send_goal_status(
        self,
        chat_id: str,
        status: str,
        *,
        started_at: float | None = None,
        turn_id: str | None = None,
    ) -> None: ...

    async def send_turn_end(
        self,
        chat_id: str,
        latency_ms: int | None = None,
        *,
        goal_state: dict[str, Any] | None = None,
        usage: LLMUsage | None = None,
        context_window_tokens: int | None = None,
        metadata: dict[str, Any] | None = None,
        turn_owner: str | None = None,
    ) -> None: ...

    async def send_session_updated(self, chat_id: str, *, scope: str | None = None) -> None: ...

    async def send_file_edit_events(
        self,
        chat_id: str,
        edits: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def send_projected_message(
        self,
        msg: OutboundMessage,
        progress_event: ProgressEvent | None,
    ) -> None: ...


class WebUIOutboundProjector:
    """Interpret runtime events without coupling that state machine to the channel."""

    def __init__(
        self,
        transport: WebUIOutboundTransport,
        session_projection: WebUISessionProjection,
    ) -> None:
        self._transport = transport
        self._session_projection = session_projection

    async def hydrate(self, chat_id: str) -> None:
        """Replay reconnect state through the existing stable wire operations."""
        for event in self._session_projection.hydration_events(
            webui_session_key(chat_id),
            chat_id,
        ):
            if event["event"] == "goal_state":
                await self._transport.send_goal_state(chat_id, event["goal_state"])
                continue
            await self._transport.send_goal_status(
                chat_id,
                "running",
                started_at=event["started_at"],
                turn_id=event.get("turn_id"),
            )

    async def send(self, msg: OutboundMessage) -> None:
        event = outbound_event_from_message(msg)
        progress_event = event if isinstance(event, ProgressEvent) else None
        if isinstance(event, RuntimeModelUpdatedEvent):
            await self._transport.send_runtime_model_updated(
                model_name=event.model,
                model_preset=event.model_preset,
            )
            return

        conns = list(self._transport.webui_subscribers(msg.chat_id))
        if not conns:
            quiet_events = (
                ProgressEvent,
                UserInputEvent,
                TurnEndEvent,
                SessionUpdatedEvent,
                GoalStatusEvent,
                GoalStateSyncEvent,
            )
            log = (
                logger.debug
                if isinstance(event, quiet_events)
                else logger.warning
            )
            log("no active subscribers for chat_id={}", msg.chat_id)

        if isinstance(event, TurnModelUpdatedEvent):
            if conns:
                await self._transport.send_turn_model_updated(
                    msg.chat_id,
                    model_name=event.model,
                    model_preset=event.model_preset,
                    context_window_tokens=event.context_window_tokens,
                    fallback=event.fallback,
                )
            return
        if isinstance(event, UserInputEvent):
            if conns:
                await self._transport.send_user_input(
                    msg.chat_id,
                    content=event.content,
                    created_at_ms=event.created_at_ms,
                    provenance=event.provenance,
                )
            return
        if isinstance(event, RecoveryStateEvent):
            if conns:
                await self._transport.send_recovery_state(msg.chat_id, event)
            return
        if isinstance(event, GoalStateSyncEvent):
            if conns:
                await self._transport.send_goal_state(
                    msg.chat_id,
                    event.goal_state or {"active": False},
                )
            return
        if isinstance(event, GoalStatusEvent):
            turn_id = (msg.metadata or {}).get(WEBUI_TURN_METADATA_KEY)
            current_turn_id = turn_id if isinstance(turn_id, str) else None
            turn_owner = (msg.metadata or {}).get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            current_turn_owner = turn_owner if isinstance(turn_owner, str) else None
            try:
                if conns and event.status in ("running", "idle"):
                    await self._transport.send_goal_status(
                        msg.chat_id,
                        event.status,
                        started_at=event.started_at,
                        turn_id=current_turn_id,
                    )
            finally:
                if event.status == "idle":
                    clear_websocket_turn_if_current(
                        msg.chat_id,
                        current_turn_owner,
                        preserve_persistence_failure=True,
                    )
            return
        if isinstance(event, TurnEndEvent):
            turn_id = (msg.metadata or {}).get(WEBUI_TURN_METADATA_KEY)
            session_update_scope = (
                "metadata"
                if isinstance(turn_id, str)
                and turn_id.startswith(WEBUI_SYSTEM_COMMAND_TURN_PREFIX)
                else "thread"
            )
            turn_owner = (msg.metadata or {}).get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            await self._transport.send_turn_end(
                msg.chat_id,
                latency_ms=event.latency_ms,
                goal_state=event.goal_state,
                usage=event.usage,
                context_window_tokens=event.context_window_tokens,
                metadata=msg.metadata,
                turn_owner=turn_owner if isinstance(turn_owner, str) else None,
            )
            await self._transport.send_session_updated(msg.chat_id, scope=session_update_scope)
            return
        if isinstance(event, SessionUpdatedEvent):
            if conns:
                await self._transport.send_session_updated(msg.chat_id, scope=event.scope)
            return
        if progress_event and progress_event.file_edit_events:
            await self._transport.send_file_edit_events(
                msg.chat_id,
                progress_event.file_edit_events,
                msg.metadata,
            )
            return
        await self._transport.send_projected_message(msg, progress_event)
