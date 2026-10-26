"""Own WebUI outbound projection, stream state and durable delivery completion."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias

from loguru import logger

from nanobot.bus.events import INBOUND_META_USER_SHELL, OUTBOUND_META_AGENT_UI, OutboundMessage
from nanobot.bus.outbound_events import (
    ContextCompactionEvent,
    GoalStateSyncEvent,
    GoalStatusEvent,
    ProgressEvent,
    RetryStatusEvent,
    RetryWaitEvent,
    RuntimeModelUpdatedEvent,
    SessionUpdatedEvent,
    TurnEndEvent,
    TurnModelUpdatedEvent,
    UserInputEvent,
)
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import SubagentTaskChanged
from nanobot.pairing.events import PairingChanged
from nanobot.session.webui_turns import (
    clear_websocket_turn_if_current,
    mark_websocket_turn_transcript_persistence_failed,
    websocket_turn_transcript_persistence_failed,
)
from nanobot.webui.media_gateway import WebUIMediaGateway
from nanobot.webui.metadata import (
    WEBSOCKET_TURN_OWNER_METADATA_KEY,
    WEBUI_RESTART_CONTROL_METADATA_KEY,
    WEBUI_SYSTEM_COMMAND_TURN_PREFIX,
    WEBUI_TURN_METADATA_KEY,
)
from nanobot.webui.outbound_wire import (
    FileEditWirePayload,
    GoalStateWirePayload,
    GoalStatusWirePayload,
    MessageWirePayload,
    RuntimeModelWirePayload,
    SessionUpdatedWirePayload,
    StreamWirePayload,
    TurnModelWirePayload,
    UserInputWirePayload,
    WebUIWirePayload,
    WebUIWirePersistence,
    encode_turn_end,
    project_notification,
    project_tool_events,
)
from nanobot.webui.session_identity import webui_session_key
from nanobot.webui.session_projection import WebUISessionProjection
from nanobot.webui.temporary_chats import WebUITemporaryChats
from nanobot.webui.transcript import WEBUI_TRANSCRIPT_INCOMPLETE_KEY, WebUITranscriptRecorder

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection


@dataclass(frozen=True)
class ChatAudience:
    chat_id: str


WebUIAudience: TypeAlias = ChatAudience | Literal["all_connections", "authenticated_webui"]


class WebUIOutboundTransport(Protocol):
    """Snapshot recipients and enqueue already projected public JSON frames."""

    def webui_recipients(self, audience: WebUIAudience) -> tuple[ServerConnection, ...]: ...

    async def webui_send_raw(
        self, connection: ServerConnection, raw: str, *, label: str = "",
    ) -> None: ...


class WebUIOutboundDelivery:
    """Keep presentation, history and delivery-turn policy out of socket writers."""

    def __init__(
        self,
        transport: WebUIOutboundTransport,
        *,
        media: WebUIMediaGateway,
        transcripts: WebUITranscriptRecorder,
        temporary_chats: WebUITemporaryChats,
        session_projection: WebUISessionProjection,
    ) -> None:
        self._transport = transport
        self._media = media
        self._transcripts = transcripts
        self._temporary_chats = temporary_chats
        self._session_projection = session_projection
        self._stream_text_buffers: dict[tuple[str, str], list[str]] = {}
        self._reasoning_text_buffers: dict[tuple[str, str], list[str]] = {}

    async def initialize(self) -> None:
        await self._transcripts.initialize()

    def bind_pairing(self, bus: MessageBus, *, channel: str) -> Callable[[], None]:
        async def queue_changed(event: PairingChanged) -> None:
            await bus.publish_event(event, channel=channel, chat_id="*")

        return bus.subscribe(queue_changed, PairingChanged)

    def discard(self, chat_id: str) -> None:
        """Forget unclosed streams when a turn ends or its chat is discarded."""
        for buffers in (self._stream_text_buffers, self._reasoning_text_buffers):
            for key in tuple(buffers):
                if key[0] == chat_id:
                    buffers.pop(key, None)

    async def hydrate(self, chat_id: str) -> None:
        for event in await self._session_projection.hydration_events(
            webui_session_key(chat_id), chat_id,
        ):
            if event["event"] == "goal_state":
                await self._send_goal_state(chat_id, event["goal_state"])
            else:
                await self._send_goal_status(
                    chat_id, "running", started_at=event["started_at"], turn_id=event.get("turn_id"),
                )

    async def _fanout(
        self,
        recipients: tuple[ServerConnection, ...],
        payload: Mapping[str, object],
        *,
        label: str,
    ) -> None:
        raw = json.dumps(payload, ensure_ascii=False)
        for connection in recipients:
            await self._transport.webui_send_raw(connection, raw, label=label)

    async def send(self, msg: OutboundMessage) -> None:
        event = msg.event
        if isinstance(event, PairingChanged):
            await self._fanout(
                self._transport.webui_recipients("authenticated_webui"),
                {"event": "pairing_changed"},
                label=" pairing_changed ",
            )
            return
        if isinstance(event, RetryWaitEvent):
            return
        if isinstance(event, RuntimeModelUpdatedEvent):
            await self._send_runtime_model_updated(event.model, event.model_preset)
            return

        recipients = self._transport.webui_recipients(ChatAudience(msg.chat_id))
        if not recipients:
            quiet_events = (
                ProgressEvent, RetryStatusEvent, UserInputEvent, TurnEndEvent, SessionUpdatedEvent,
                GoalStatusEvent, GoalStateSyncEvent, SubagentTaskChanged, ContextCompactionEvent,
            )
            log = logger.debug if isinstance(event, quiet_events) else logger.warning
            log("no active subscribers for chat_id={}", msg.chat_id)

        if isinstance(event, TurnModelUpdatedEvent):
            if recipients:
                await self._send_turn_model_updated(msg.chat_id, event)
            return
        if isinstance(event, UserInputEvent):
            if recipients:
                body: UserInputWirePayload = {
                    "event": "user_message", "chat_id": msg.chat_id, "text": event.content,
                    "created_at_ms": event.created_at_ms, "starts_turn": False,
                }
                if event.provenance:
                    body["provenance"] = event.provenance
                await self._fanout(recipients, body, label=" user_message ")
            return
        notification = project_notification(msg.chat_id, event, msg.metadata)
        if notification is not None:
            if recipients or notification.deliver_offline:
                await self._send_payload(
                    msg.chat_id, notification.payload, persistence=notification.persistence,
                    metadata=msg.metadata if notification.attach_turn_metadata else None,
                )
            return
        if isinstance(event, GoalStateSyncEvent):
            if recipients:
                await self._send_goal_state(msg.chat_id, event.goal_state or {"active": False})
            return
        if isinstance(event, GoalStatusEvent):
            turn_id = msg.metadata.get(WEBUI_TURN_METADATA_KEY)
            turn_owner = msg.metadata.get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            owner = turn_owner if isinstance(turn_owner, str) else None
            try:
                if recipients and event.status in ("running", "idle"):
                    await self._send_goal_status(
                        msg.chat_id, event.status, started_at=event.started_at,
                        turn_id=turn_id if isinstance(turn_id, str) else None,
                    )
            finally:
                if event.status == "idle":
                    clear_websocket_turn_if_current(
                        msg.chat_id, owner, preserve_persistence_failure=True,
                    )
            return
        if isinstance(event, TurnEndEvent):
            turn_id = msg.metadata.get(WEBUI_TURN_METADATA_KEY)
            scope = (
                "metadata" if isinstance(turn_id, str)
                and turn_id.startswith(WEBUI_SYSTEM_COMMAND_TURN_PREFIX) else "thread"
            )
            turn_owner = msg.metadata.get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            await self._send_payload(
                msg.chat_id, encode_turn_end(msg.chat_id, event, msg.metadata),
                persistence="turn_complete", metadata=msg.metadata,
                turn_owner=turn_owner if isinstance(turn_owner, str) else None,
            )
            await self.session_updated(msg.chat_id, scope=scope)
            return
        if isinstance(event, SubagentTaskChanged):
            if recipients:
                task = self._session_projection.subagent_task(webui_session_key(msg.chat_id), event.task_id)
                if task is not None:
                    await self._send_payload(
                        msg.chat_id, {"event": "subagent_task", "chat_id": msg.chat_id, "task": task},
                        persistence="transient",
                    )
            return
        if isinstance(event, SessionUpdatedEvent):
            if recipients:
                await self.session_updated(msg.chat_id, scope=event.scope)
            return
        progress = event if isinstance(event, ProgressEvent) else None
        if progress and progress.file_edit_events:
            await self.send_file_edit_events(msg.chat_id, progress.file_edit_events, msg.metadata)
            return
        await self._send_message(msg, progress)

    async def _persist_turn_transcript_event(
        self,
        chat_id: str,
        event: dict[str, Any],
        *,
        metadata: dict[str, Any] | None,
        phase: str,
        include_source: bool = False,
        transcript_overrides: dict[str, Any] | None = None,
    ) -> bool:
        if (
            (metadata or {}).get(WEBUI_RESTART_CONTROL_METADATA_KEY) is True
            or not self._temporary_chats.should_persist_transcript(chat_id)
        ):
            self._transcripts.prepare_event(
                chat_id, event, metadata=metadata, phase=phase, include_source=include_source,
            )
            return True
        persisted = await self._transcripts.prepare_and_append(
            chat_id, event, metadata=metadata, phase=phase, include_source=include_source,
            transcript_overrides=transcript_overrides,
        )
        return self._retain_turn_on_transcript_failure(
            chat_id, persisted=persisted, metadata=metadata, phase=phase,
        )

    @staticmethod
    def _retain_turn_on_transcript_failure(
        chat_id: str,
        *,
        persisted: bool,
        metadata: dict[str, Any] | None,
        phase: str,
    ) -> bool:
        if not persisted and phase in {"answer", "complete"} and (metadata or {}).get("webui") is True:
            owner = (metadata or {}).get(WEBSOCKET_TURN_OWNER_METADATA_KEY)
            mark_websocket_turn_transcript_persistence_failed(
                chat_id, owner if isinstance(owner, str) else None,
            )
        return persisted

    async def _persist_turn_stream_event(
        self,
        chat_id: str,
        event: dict[str, Any],
        *,
        completed_text: str | None,
        metadata: dict[str, Any] | None,
        phase: str,
        include_source: bool = False,
    ) -> bool:
        if not self._temporary_chats.should_persist_transcript(chat_id):
            self._transcripts.prepare_event(
                chat_id, event, metadata=metadata, phase=phase, include_source=include_source,
            )
            return True
        persisted = await self._transcripts.prepare_and_append_stream_event(
            chat_id, event, completed_text=completed_text, metadata=metadata,
            phase=phase, include_source=include_source,
        )
        return self._retain_turn_on_transcript_failure(
            chat_id, persisted=persisted, metadata=metadata, phase=phase,
        )

    async def _send_message(self, msg: OutboundMessage, progress: ProgressEvent | None) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(msg.chat_id))
        text = msg.content
        user_shell = msg.metadata.get(INBOUND_META_USER_SHELL) is True
        payload: MessageWirePayload = {
            "event": "message", "chat_id": msg.chat_id,
            "text": text if user_shell else self._media.rewrite_local_markdown_images(text),
        }
        if user_shell:
            payload["render_as"] = "text"
        turn_id = msg.metadata.get(WEBUI_TURN_METADATA_KEY)
        if isinstance(turn_id, str) and turn_id:
            payload["turn_id"] = turn_id
        if msg.media:
            payload["media"] = msg.media
            urls: list[dict[str, str]] = []
            for entry in msg.media:
                signed = self._media.sign_or_stage_media_path(Path(entry))
                if signed is not None:
                    urls.append(signed)
            if urls:
                payload["media_urls"] = urls
        if msg.reply_to:
            payload["reply_to"] = msg.reply_to
        latency = msg.metadata.get("latency_ms")
        if isinstance(latency, (int, float)):
            payload["latency_ms"] = int(latency)
        if progress and progress.tool_events:
            payload["tool_events"] = project_tool_events(progress.tool_events)
        agent_ui = msg.metadata.get(OUTBOUND_META_AGENT_UI)
        if agent_ui is not None:
            payload["agent_ui"] = agent_ui
        if progress:
            payload["kind"] = "tool_hint" if progress.tool_hint else "progress"
        body: dict[str, Any] = dict(payload)
        await self._persist_turn_transcript_event(
            msg.chat_id, body, metadata=msg.metadata,
            phase="activity" if progress else "answer", include_source=True,
            transcript_overrides={"text": text},
        )
        await self._fanout(recipients, body, label=" ")

    async def send_reasoning_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None,
        *, stream_id: str | None = None,
    ) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(chat_id))
        if not delta:
            return
        payload: StreamWirePayload = {"event": "reasoning_delta", "chat_id": chat_id, "text": delta}
        if stream_id is not None:
            payload["stream_id"] = stream_id
        self._reasoning_text_buffers.setdefault((chat_id, str(stream_id or "")), []).append(delta)
        body: dict[str, Any] = dict(payload)
        await self._persist_turn_stream_event(
            chat_id, body, completed_text=None, metadata=metadata or {}, phase="reasoning",
        )
        await self._fanout(recipients, body, label=" reasoning ")

    async def send_reasoning_end(
        self, chat_id: str, metadata: dict[str, Any] | None = None,
        *, stream_id: str | None = None,
    ) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(chat_id))
        payload: StreamWirePayload = {"event": "reasoning_end", "chat_id": chat_id}
        if stream_id is not None:
            payload["stream_id"] = stream_id
        text = "".join(self._reasoning_text_buffers.pop((chat_id, str(stream_id or "")), []))
        body: dict[str, Any] = dict(payload)
        await self._persist_turn_stream_event(
            chat_id, body, completed_text=text or None, metadata=metadata or {}, phase="reasoning",
        )
        await self._fanout(recipients, body, label=" reasoning_end ")

    async def send_file_edit_events(
        self, chat_id: str, edits: list[dict[str, Any]], metadata: dict[str, Any] | None = None,
    ) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(chat_id))
        payload: FileEditWirePayload = {"event": "file_edit", "chat_id": chat_id, "edits": edits}
        body: dict[str, Any] = dict(payload)
        await self._persist_turn_transcript_event(chat_id, body, metadata=metadata, phase="activity")
        await self._fanout(recipients, body, label=" file_edit ")

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
        stream_end: bool = False,
        resuming: bool = False,
        merge_next: bool = False,
    ) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(chat_id))
        stream_key = (chat_id, str(stream_id or ""))
        completed_text: str | None = None
        payload: StreamWirePayload
        if stream_end:
            payload = {"event": "stream_end", "chat_id": chat_id}
            buffered = (
                self._stream_text_buffers.setdefault(stream_key, [])
                if merge_next else self._stream_text_buffers.pop(stream_key, [])
            )
            if delta:
                buffered.append(delta)
            full_text = "".join(buffered)
            rewritten = self._media.rewrite_local_markdown_images(full_text)
            completed_text = rewritten
            if delta or rewritten != full_text:
                payload["text"] = rewritten
        else:
            payload = {"event": "delta", "chat_id": chat_id, "text": delta}
            self._stream_text_buffers.setdefault(stream_key, []).append(delta)
        if stream_id is not None:
            payload["stream_id"] = stream_id
        if stream_end and resuming:
            payload["resuming"] = True
        if stream_end and merge_next:
            payload["merge_next"] = True
        body: dict[str, Any] = dict(payload)
        await self._persist_turn_stream_event(
            chat_id, body, completed_text=completed_text, metadata=metadata or {},
            phase="answer", include_source=True,
        )
        await self._fanout(recipients, body, label=" stream ")

    async def _send_payload(
        self,
        chat_id: str,
        payload: WebUIWirePayload,
        *,
        persistence: WebUIWirePersistence,
        metadata: dict[str, Any] | None = None,
        turn_owner: str | None = None,
    ) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(chat_id))
        body: dict[str, Any] = dict(payload)
        if persistence == "turn_activity":
            await self._persist_turn_transcript_event(chat_id, body, metadata=metadata, phase="activity")
        elif persistence == "turn_complete":
            prior_failure = (
                (metadata or {}).get("webui") is True
                and websocket_turn_transcript_persistence_failed(chat_id, turn_owner)
            )
            persisted = await self._persist_turn_transcript_event(
                chat_id, body, metadata=metadata, phase="complete",
                transcript_overrides={WEBUI_TRANSCRIPT_INCOMPLETE_KEY: True} if prior_failure else None,
            )
            if persisted:
                # A durable incomplete marker allows HTTP recovery after restart.
                clear_websocket_turn_if_current(chat_id, turn_owner)
            self.discard(chat_id)
        await self._fanout(recipients, body, label=f" {body['event']} ")

    async def _send_goal_state(self, chat_id: str, blob: dict[str, Any]) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(chat_id))
        if recipients:
            payload: GoalStateWirePayload = {"event": "goal_state", "chat_id": chat_id, "goal_state": blob}
            await self._fanout(recipients, payload, label=" goal_state ")

    async def _send_goal_status(
        self, chat_id: str, status: str, *, started_at: float | None = None, turn_id: str | None = None,
    ) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(chat_id))
        if not recipients:
            return
        payload: GoalStatusWirePayload = {"event": "goal_status", "chat_id": chat_id, "status": status}
        if status == "running" and started_at is not None:
            payload["started_at"] = started_at
        if turn_id:
            payload["turn_id"] = turn_id
        await self._fanout(recipients, payload, label=" goal_status ")

    async def session_updated(self, chat_id: str, *, scope: str | None = None) -> None:
        recipients = self._transport.webui_recipients("all_connections")
        if not recipients:
            return
        payload: SessionUpdatedWirePayload = {"event": "session_updated", "chat_id": chat_id}
        if scope:
            payload["scope"] = scope
        await self._fanout(recipients, payload, label=" session_updated ")

    async def _send_runtime_model_updated(self, model_name: str | None, model_preset: str | None) -> None:
        recipients = self._transport.webui_recipients("all_connections")
        if not recipients or not isinstance(model_name, str) or not model_name.strip():
            return
        payload: RuntimeModelWirePayload = {"event": "runtime_model_updated", "model_name": model_name.strip()}
        if isinstance(model_preset, str) and model_preset.strip():
            payload["model_preset"] = model_preset.strip()
        await self._fanout(recipients, payload, label=" runtime_model_updated ")

    async def _send_turn_model_updated(self, chat_id: str, event: TurnModelUpdatedEvent) -> None:
        recipients = self._transport.webui_recipients(ChatAudience(chat_id))
        if not recipients or not event.model.strip():
            return
        payload: TurnModelWirePayload = {
            "event": "turn_model_updated", "chat_id": chat_id, "model_name": event.model.strip(),
        }
        if isinstance(event.model_preset, str) and event.model_preset.strip():
            payload["model_preset"] = event.model_preset.strip()
        if isinstance(event.context_window_tokens, int) and event.context_window_tokens > 0:
            payload["context_window_tokens"] = event.context_window_tokens
        if event.fallback:
            payload["fallback"] = True
            if event.reauth_provider:
                payload["reauth_provider"] = event.reauth_provider
        await self._fanout(recipients, payload, label=" turn_model_updated ")
