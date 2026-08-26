"""Application orchestration for typed WebUI WebSocket commands."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from loguru import logger
from websockets.asyncio.server import ServerConnection

from nanobot.bus.events import INBOUND_META_USER_SHELL
from nanobot.command.builtin import USER_SHELL_COMMAND, builtin_command_starts_agent_turn
from nanobot.runtime_context import (
    RUNTIME_CONTEXT_INPUT_META,
    WEBUI_QUOTE_METADATA,
    RuntimeContextBlock,
    webui_quote_runtime_context,
)
from nanobot.security.workspace_access import (
    WORKSPACE_SCOPE_METADATA_KEY,
    WorkspaceScopeError,
)
from nanobot.session.webui_turns import (
    clear_websocket_turn_if_current,
    clear_websocket_turns,
    register_queued_websocket_turn_if_idle,
    websocket_turn_id,
    websocket_turn_wall_started_at,
)
from nanobot.utils.helpers import safe_filename
from nanobot.webui.cli_apps_api import normalize_cli_app_mentions
from nanobot.webui.forking import handle_webui_fork_chat
from nanobot.webui.gateway_services import GatewayServices
from nanobot.webui.mcp_presets_api import normalize_mcp_preset_mentions
from nanobot.webui.metadata import WEBSOCKET_TURN_OWNER_METADATA_KEY
from nanobot.webui.session_access import (
    SessionMention,
    WebuiSessionAccess,
    session_mentions_runtime_context,
)
from nanobot.webui.session_identity import is_valid_webui_chat_id, webui_session_key
from nanobot.webui.sidebar_state import write_webui_sidebar_state
from nanobot.webui.temporary_chats import TemporaryChatError
from nanobot.webui.transcription_ws import webui_transcription_event

_WEBUI_REQUEST_CACHE_TTL_S = 5 * 60.0
_WEBUI_REQUEST_CACHE_MAX = 256


@dataclass(frozen=True)
class WebUIRequestResult:
    result: Any = None
    status: int | None = None
    message: str | None = None


@dataclass
class WebUIRequestOperation:
    action: str
    payload_digest: bytes
    task: asyncio.Task[WebUIRequestResult]
    completed_at: float | None = None


class WebUICommandTransport(Protocol):
    """Typed transport capabilities consumed by WebUI command orchestration."""

    def is_allowed(self, sender_id: str) -> bool: ...

    def webui_subscribers(self, chat_id: str) -> tuple[ServerConnection, ...]: ...

    def webui_connection_chats(self, connection: ServerConnection) -> tuple[str, ...]: ...

    def webui_attach(self, connection: ServerConnection, chat_id: str) -> None: ...

    def webui_detach(self, connection: ServerConnection, chat_id: str) -> None: ...

    def webui_clear_connection_default(self, connection: ServerConnection) -> None: ...

    def webui_clear_stream_buffers(self, chat_id: str) -> None: ...

    async def webui_hydrate(self, chat_id: str) -> None: ...

    async def webui_send_event(
        self,
        connection: ServerConnection,
        event: str,
        **fields: Any,
    ) -> None: ...

    async def webui_send_raw(
        self,
        connection: ServerConnection,
        raw: str,
        *,
        label: str = "",
    ) -> None: ...

    async def webui_dispatch_message(
        self,
        *,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None,
        metadata: dict[str, Any],
        is_dm: bool,
        session_key: str | None,
        require_existing_session: bool,
    ) -> None: ...

    async def send_session_updated(
        self,
        chat_id: str,
        *,
        scope: str | None = None,
    ) -> None: ...


class WebUICommandRouter:
    """Own WebUI command semantics while a transport host owns raw connections."""

    def __init__(self, transport: WebUICommandTransport, gateway: GatewayServices) -> None:
        self._transport = transport
        self.gateway = gateway
        self._http_router = gateway.http
        self._media = gateway.media
        self._ingress = gateway.ingress
        self._transcripts = gateway.transcripts
        self._workspaces = gateway.workspaces
        self._temporary_chats = gateway.temporary_chats
        self._session_projection = gateway.session_projection
        self._webui_connections = gateway.endpoint.webui_connections
        self._session_access = (
            WebuiSessionAccess(gateway.session_manager)
            if gateway.session_manager is not None
            else None
        )
        self.request_tasks: dict[
            tuple[ServerConnection, str],
            asyncio.Task[None],
        ] = {}
        self.request_operations: dict[str, WebUIRequestOperation] = {}
        self.request_locks: dict[ServerConnection, asyncio.Lock] = {}

    def workspace_controls_available(self, connection: ServerConnection) -> bool:
        return self._http_router.workspace_controls_available(connection)

    async def send_webui_protocol_error(
        self,
        connection: ServerConnection,
        detail: str,
    ) -> None:
        await self._transport.webui_send_event(connection, "error", detail=detail)

    async def attach_webui_fork(
        self,
        connection: ServerConnection,
        *,
        fork_id: str,
        fork_key: str,
    ) -> None:
        scope = self._workspaces.scope_for_session_key(fork_key)
        self._transport.webui_attach(connection, fork_id)
        await self._transport.webui_send_event(
            connection,
            "attached",
            chat_id=fork_id,
            **self._session_projection.attach_fields(fork_key),
        )
        await self._transport.webui_send_event(
            connection,
            "session_updated",
            chat_id=fork_id,
            scope="metadata",
            workspace_scope=scope.payload(),
        )
        await self._transport.webui_hydrate(fork_id)

    async def discard_owned_chat(
        self,
        connection: ServerConnection,
        chat_id: str,
    ) -> None:
        await self._temporary_chats.discard(connection, chat_id)
        self._transport.webui_detach(connection, chat_id)
        clear_websocket_turns(chat_id)
        self._transport.webui_clear_stream_buffers(chat_id)

    async def cleanup_connection(self, connection: ServerConnection) -> None:
        """Release command-owned state associated with one transport connection."""
        chat_ids = self._transport.webui_connection_chats(connection)
        for chat_id in chat_ids:
            if self._temporary_chats.owns(connection, chat_id):
                await self.discard_owned_chat(connection, chat_id)
            else:
                self._transport.webui_detach(connection, chat_id)
        for chat_id in self._temporary_chats.chat_ids_for_owner(connection):
            await self.discard_owned_chat(connection, chat_id)
        self._transport.webui_clear_connection_default(connection)
        self.gateway.endpoint.discard_connection(connection)
        self.discard_request_lock_if_idle(connection)

    async def broadcast_webui_event(self, event: str, **fields: Any) -> None:
        for connection in tuple(self._webui_connections):
            await self._transport.webui_send_event(connection, event, **fields)

    async def broadcast_user_message(
        self,
        origin: ServerConnection,
        chat_id: str,
        text: str,
        *,
        turn_id: str | None,
        starts_turn: bool,
        media_paths: list[str],
        media_names: list[str | None],
        cli_apps: list[dict[str, Any]],
        mcp_presets: list[dict[str, Any]],
        session_mentions: list[SessionMention],
    ) -> None:
        body: dict[str, Any] = {
            "event": "user_message",
            "chat_id": chat_id,
            "text": text,
            "starts_turn": starts_turn,
        }
        if turn_id is not None:
            body["turn_id"] = turn_id
        media = self._media.augment_transcript_user_media(media_paths)
        for attachment, name in zip(media, media_names, strict=False):
            if name:
                attachment["name"] = name
        if media:
            body["media_urls"] = media
        if cli_apps:
            body["cli_apps"] = cli_apps
        if mcp_presets:
            body["mcp_presets"] = mcp_presets
        if session_mentions:
            body["session_mentions"] = session_mentions
        active_turn_id = websocket_turn_id(chat_id)
        if active_turn_id is not None:
            body["active_turn_id"] = active_turn_id
        started_at = websocket_turn_wall_started_at(chat_id)
        if active_turn_id is not None and started_at is not None:
            body["started_at"] = started_at
        raw = json.dumps(body, ensure_ascii=False)
        for connection in self._transport.webui_subscribers(chat_id):
            if connection is not origin:
                await self._transport.webui_send_raw(connection, raw, label=" user_message ")

    async def workspace_scope_or_error(
        self,
        connection: ServerConnection,
        resolver: Callable[[], Any],
        *,
        chat_id: str | None = None,
        turn_id: str | None = None,
    ) -> Any | None:
        try:
            return resolver()
        except WorkspaceScopeError as exc:
            await self._transport.webui_send_event(
                connection,
                "error",
                detail="workspace_scope_rejected",
                reason=exc.message,
                **({"chat_id": chat_id} if chat_id else {}),
                **({"turn_id": turn_id} if turn_id else {}),
            )
            return None

    async def dispatch(
        self,
        connection: ServerConnection,
        client_id: str,
        envelope: dict[str, Any],
    ) -> None:
        """Execute one typed WebUI command."""
        command_type = envelope.get("type")
        if command_type == "webui_request":
            await self.start_webui_request(connection, envelope)
            return
        if command_type == "new_chat":
            new_id = str(uuid.uuid4())
            scope = await self.workspace_scope_or_error(
                connection,
                lambda: self._workspaces.scope_for_new_chat(
                    envelope,
                    controls_available=self.workspace_controls_available(connection),
                ),
            )
            if scope is None:
                return
            self._workspaces.stage_scope(new_id, scope)
            self._transport.webui_attach(connection, new_id)
            await self._transport.webui_send_event(
                connection,
                "attached",
                chat_id=new_id,
                **self._session_projection.attach_fields(webui_session_key(new_id)),
            )
            await self._transport.webui_send_event(
                connection,
                "session_updated",
                chat_id=new_id,
                scope="metadata",
                workspace_scope=scope.payload(),
            )
            await self._transport.webui_hydrate(new_id)
            return
        if command_type == "new_temporary_chat":
            try:
                new_id = self._temporary_chats.create(
                    connection,
                    trusted_webui=connection in self._webui_connections,
                )
            except TemporaryChatError as exc:
                await self._transport.webui_send_event(connection, "error", detail=exc.detail)
                return
            self._transport.webui_attach(connection, new_id)
            await self._transport.webui_send_event(
                connection,
                "attached",
                chat_id=new_id,
                temporary=True,
            )
            return
        if command_type == "fork_chat":
            await handle_webui_fork_chat(self, connection, envelope)
            return
        if command_type == "discard_temporary_chat":
            chat_id = envelope.get("chat_id")
            if not is_valid_webui_chat_id(chat_id):
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail="invalid temporary chat_id",
                )
                return
            try:
                await self.discard_owned_chat(connection, chat_id)
            except TemporaryChatError as exc:
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail=exc.detail,
                    chat_id=chat_id,
                )
            return
        if command_type == "attach":
            chat_id = envelope.get("chat_id")
            if not is_valid_webui_chat_id(chat_id):
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail="invalid chat_id",
                )
                return
            try:
                self._temporary_chats.validate_attach(chat_id)
            except TemporaryChatError as exc:
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail=exc.detail,
                    chat_id=chat_id,
                )
                return
            self._transport.webui_attach(connection, chat_id)
            await self._transport.webui_send_event(
                connection,
                "attached",
                chat_id=chat_id,
                **self._session_projection.attach_fields(webui_session_key(chat_id)),
            )
            await self._transport.webui_hydrate(chat_id)
            return
        if command_type == "set_sidebar_state":
            if connection not in self._webui_connections:
                await self._transport.webui_send_event(connection, "error", detail="access_denied")
                return
            state = envelope.get("state")
            if not isinstance(state, dict):
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail="invalid_sidebar_state",
                )
                return
            try:
                saved_state = await asyncio.to_thread(
                    write_webui_sidebar_state,
                    cast(dict[str, Any], state),
                )
            except (OSError, ValueError):
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail="invalid_sidebar_state",
                )
                return
            await self.broadcast_webui_event("sidebar_state_updated", state=saved_state)
            return
        if command_type == "set_workspace_scope":
            chat_id = envelope.get("chat_id")
            if not is_valid_webui_chat_id(chat_id):
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail="invalid chat_id",
                )
                return
            try:
                self._temporary_chats.validate_workspace_update(chat_id)
            except TemporaryChatError as exc:
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail=exc.detail,
                    chat_id=chat_id,
                )
                return
            scope = await self.workspace_scope_or_error(
                connection,
                lambda: self._workspaces.scope_for_set_request(
                    envelope,
                    chat_id=chat_id,
                    chat_running=websocket_turn_wall_started_at(chat_id) is not None,
                    controls_available=self.workspace_controls_available(connection),
                ),
                chat_id=chat_id,
            )
            if scope is None:
                return
            self._workspaces.stage_scope(chat_id, scope)
            await self._transport.send_session_updated(chat_id, scope="metadata")
            await self._transport.webui_send_event(
                connection,
                "session_updated",
                chat_id=chat_id,
                scope="metadata",
                workspace_scope=scope.payload(),
            )
            return
        if command_type == "transcribe_audio":
            event, payload = await webui_transcription_event(
                envelope,
                config_path=self.gateway.settings.config.path,
            )
            await self._transport.webui_send_event(connection, event, **payload)
            return
        if command_type == "message":
            await self._dispatch_message(connection, client_id, envelope)
            return
        await self._transport.webui_send_event(
            connection,
            "error",
            detail=f"unknown type: {command_type!r}",
        )

    async def _dispatch_message(
        self,
        connection: ServerConnection,
        client_id: str,
        envelope: dict[str, Any],
    ) -> None:
        chat_id = envelope.get("chat_id")
        content = envelope.get("content")
        if not is_valid_webui_chat_id(chat_id):
            await self._transport.webui_send_event(connection, "error", detail="invalid chat_id")
            return
        raw_turn_id = envelope.get("turn_id")
        turn_id = raw_turn_id if isinstance(raw_turn_id, str) and raw_turn_id else None
        rejection_fields = {
            "chat_id": chat_id,
            **({"turn_id": turn_id} if turn_id else {}),
        }
        if not self._transport.is_allowed(client_id):
            await self._transport.webui_send_event(
                connection,
                "error",
                detail="access_denied",
                **rejection_fields,
            )
            return
        if not isinstance(content, str):
            await self._transport.webui_send_event(
                connection,
                "error",
                detail="missing content",
                **rejection_fields,
            )
            return
        message_rejection = self._ingress.validate_text(content)
        if message_rejection is not None:
            await self._transport.webui_send_event(
                connection,
                "error",
                detail="message_rejected",
                reason=message_rejection,
                **rejection_fields,
            )
            return

        try:
            temporary_policy = self._temporary_chats.message_policy(
                connection,
                chat_id,
                content,
            )
        except TemporaryChatError as exc:
            await self._transport.webui_send_event(
                connection,
                "error",
                detail=exc.detail,
                **rejection_fields,
            )
            return

        raw_media = envelope.get("media")
        media_paths: list[str] = []
        media_names: list[str | None] = []
        if raw_media is not None:
            if not isinstance(raw_media, list):
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail="attachment_rejected",
                    reason="malformed",
                    **rejection_fields,
                )
                return
            media_paths, reason = self._media.store_inbound_attachments(
                cast(list[Any], raw_media)
            )
            if reason is not None:
                await self._transport.webui_send_event(
                    connection,
                    "error",
                    detail="attachment_rejected",
                    reason=reason,
                    **rejection_fields,
                )
                return
            for item in cast(list[Any], raw_media):
                attachment = cast(dict[str, Any], item) if isinstance(item, dict) else {}
                name = attachment.get("name")
                media_names.append((safe_filename(name) or None) if isinstance(name, str) else None)
            if temporary_policy is not None:
                self._temporary_chats.register_media(connection, chat_id, media_paths)

        if not content.strip() and not media_paths:
            await self._transport.webui_send_event(
                connection,
                "error",
                detail="missing content",
                **rejection_fields,
            )
            return
        self._transport.webui_attach(connection, chat_id)
        if temporary_policy is None or temporary_policy.hydrate_transcript:
            await self._transport.webui_hydrate(chat_id)

        scope = await self.workspace_scope_or_error(
            connection,
            lambda: (
                temporary_policy.workspace_scope
                if temporary_policy is not None
                else self._workspaces.scope_for_message(
                    envelope,
                    chat_id=chat_id,
                    chat_running=websocket_turn_wall_started_at(chat_id) is not None,
                    controls_available=self.workspace_controls_available(connection),
                )
            ),
            chat_id=chat_id,
            turn_id=turn_id,
        )
        if scope is None:
            return

        if not self._transport.is_allowed(client_id):
            await self._transport.webui_send_event(
                connection,
                "error",
                detail="access_denied",
                **rejection_fields,
            )
            return

        metadata: dict[str, Any] = {
            "remote": getattr(connection, "remote_address", None)
        }
        if envelope.get("webui") is True:
            metadata["webui"] = True
            metadata.update(self._transcripts.client_turn_metadata(envelope.get("turn_id")))
        trusted_webui = metadata.get("webui") is True and connection in self._webui_connections
        is_user_shell = (
            trusted_webui
            and envelope.get("user_shell") is True
            and content.startswith("!")
        )
        if is_user_shell:
            metadata[INBOUND_META_USER_SHELL] = True
        dispatch_content = (
            f"{USER_SHELL_COMMAND} {content[1:].lstrip()}" if is_user_shell else content
        )
        cli_apps = normalize_cli_app_mentions(envelope.get("cli_apps"))
        if cli_apps:
            metadata["cli_apps"] = cli_apps
        mcp_presets = normalize_mcp_preset_mentions(
            envelope.get("mcp_presets"),
            config_path=self.gateway.settings.config.path,
        )
        if mcp_presets:
            metadata["mcp_presets"] = mcp_presets
        session_mentions: list[SessionMention] = []
        if trusted_webui and self._session_access is not None:
            session_mentions = await asyncio.to_thread(
                self._session_access.normalize_mentions,
                envelope.get("session_mentions"),
                exclude_session_key=webui_session_key(chat_id),
            )
            if session_mentions:
                metadata["session_mentions"] = session_mentions
        metadata[WORKSPACE_SCOPE_METADATA_KEY] = scope.metadata()
        is_webui = metadata.get("webui") is True
        queued_owner = None
        if is_webui and not is_user_shell and builtin_command_starts_agent_turn(content):
            queued_owner = register_queued_websocket_turn_if_idle(chat_id, turn_id)
            if queued_owner is not None:
                metadata[WEBSOCKET_TURN_OWNER_METADATA_KEY] = queued_owner

        accepted = False
        try:
            if is_webui and (
                temporary_policy is None or temporary_policy.persist_transcript
            ):
                self._transcripts.append_user_message(
                    chat_id,
                    content,
                    metadata=metadata,
                    media_paths=media_paths or None,
                    cli_apps=cli_apps or None,
                    mcp_presets=mcp_presets or None,
                    session_mentions=session_mentions or None,
                )
            if trusted_webui:
                context_blocks: list[RuntimeContextBlock] = []
                quote = webui_quote_runtime_context(
                    {WEBUI_QUOTE_METADATA: envelope.get("quoted_context")}
                )
                if quote is not None:
                    context_blocks.append(quote)
                session_context = session_mentions_runtime_context(session_mentions)
                if session_context is not None:
                    context_blocks.append(session_context)
                if context_blocks:
                    metadata[RUNTIME_CONTEXT_INPUT_META] = context_blocks
            await self._transport.webui_dispatch_message(
                sender_id=client_id,
                chat_id=chat_id,
                content=dispatch_content,
                media=media_paths or None,
                metadata=metadata,
                is_dm=False,
                session_key=(
                    temporary_policy.session_key if temporary_policy is not None else None
                ),
                require_existing_session=(
                    temporary_policy.require_existing_session
                    if temporary_policy is not None
                    else False
                ),
            )
            self._workspaces.persist_scope(chat_id, scope)
            accepted = True
        finally:
            if not accepted and queued_owner is not None:
                clear_websocket_turn_if_current(chat_id, queued_owner)

        if is_webui:
            await self.broadcast_user_message(
                connection,
                chat_id,
                content,
                turn_id=turn_id,
                starts_turn=queued_owner is not None,
                media_paths=media_paths,
                media_names=media_names,
                cli_apps=cli_apps,
                mcp_presets=mcp_presets,
                session_mentions=session_mentions,
            )
        if is_webui and turn_id:
            active_turn_id = websocket_turn_id(chat_id)
            started_at = websocket_turn_wall_started_at(chat_id)
            await self._transport.webui_send_event(
                connection,
                "message_accepted",
                chat_id=chat_id,
                turn_id=turn_id,
                starts_turn=queued_owner is not None,
                **(
                    {"active_turn_id": active_turn_id}
                    if active_turn_id is not None
                    else {}
                ),
                **(
                    {"started_at": started_at}
                    if active_turn_id is not None and started_at is not None
                    else {}
                ),
            )

    async def start_webui_request(
        self,
        connection: ServerConnection,
        envelope: dict[str, Any],
    ) -> None:
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str) or re.fullmatch(
            r"[A-Za-z0-9._:-]{1,128}",
            request_id,
        ) is None:
            await self._transport.webui_send_event(
                connection,
                "error",
                detail="invalid webui request_id",
            )
            return
        if connection not in self._webui_connections:
            await self.send_webui_response(
                connection,
                request_id,
                status=403,
                message="access_denied",
            )
            return

        action = envelope.get("action")
        payload = envelope.get("payload")
        if not isinstance(action, str) or re.fullmatch(
            r"[a-z][a-z0-9_.]{0,127}",
            action,
        ) is None:
            await self.send_webui_response(
                connection,
                request_id,
                status=400,
                message="invalid WebUI mutation action",
            )
            return
        if not isinstance(payload, dict):
            await self.send_webui_response(
                connection,
                request_id,
                status=400,
                message="WebUI mutation payload must be an object",
            )
            return

        payload_digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).digest()
        self.prune_request_operations()
        operation = self.request_operations.get(request_id)
        is_replay = operation is not None
        if operation is not None and (
            operation.action != action or operation.payload_digest != payload_digest
        ):
            await self.send_webui_response(
                connection,
                request_id,
                status=409,
                message="request_id was already used for a different WebUI mutation",
            )
            return
        if operation is None:
            operation_task = asyncio.create_task(
                self.execute_webui_request(
                    connection,
                    action,
                    cast(dict[str, Any], payload),
                )
            )
            new_operation = WebUIRequestOperation(
                action=action,
                payload_digest=payload_digest,
                task=operation_task,
            )
            operation = new_operation
            self.request_operations[request_id] = new_operation

            def mark_complete(_task: asyncio.Task[WebUIRequestResult]) -> None:
                current = self.request_operations.get(request_id)
                if current is not new_operation:
                    return
                new_operation.completed_at = time.monotonic()
                self.prune_request_operations()

            operation_task.add_done_callback(mark_complete)

        key = (connection, request_id)
        if key in self.request_tasks:
            return
        delivery_task = asyncio.create_task(
            self.deliver_webui_request(
                connection,
                request_id,
                operation.task,
                sequence=is_replay,
            )
        )
        self.request_tasks[key] = delivery_task

    def prune_request_operations(self) -> None:
        now = time.monotonic()
        for request_id, operation in tuple(self.request_operations.items()):
            if (
                operation.completed_at is not None
                and now - operation.completed_at >= _WEBUI_REQUEST_CACHE_TTL_S
            ):
                self.request_operations.pop(request_id, None)

        completed = sorted(
            (
                (operation.completed_at, request_id)
                for request_id, operation in self.request_operations.items()
                if operation.completed_at is not None
            ),
            key=lambda item: item[0],
        )
        for _, request_id in completed[:-_WEBUI_REQUEST_CACHE_MAX]:
            self.request_operations.pop(request_id, None)

    def discard_request_lock_if_idle(self, connection: ServerConnection) -> None:
        if connection in self._webui_connections:
            return
        if any(task_connection is connection for task_connection, _ in self.request_tasks):
            return
        self.request_locks.pop(connection, None)

    async def deliver_webui_request(
        self,
        connection: ServerConnection,
        request_id: str,
        operation_task: asyncio.Task[WebUIRequestResult],
        *,
        sequence: bool = False,
    ) -> None:
        try:
            if sequence:
                lock = self.request_locks.setdefault(connection, asyncio.Lock())
                async with lock:
                    result = await asyncio.shield(operation_task)
                    await self.send_webui_response(
                        connection,
                        request_id,
                        result=result.result,
                        status=result.status,
                        message=result.message,
                    )
                return
            result = await asyncio.shield(operation_task)
            await self.send_webui_response(
                connection,
                request_id,
                result=result.result,
                status=result.status,
                message=result.message,
            )
        finally:
            self.request_tasks.pop((connection, request_id), None)
            self.discard_request_lock_if_idle(connection)

    async def execute_webui_request(
        self,
        connection: ServerConnection,
        action: str,
        payload: dict[str, Any],
    ) -> WebUIRequestResult:
        try:
            lock = self.request_locks.setdefault(connection, asyncio.Lock())
            async with lock:
                response = await self._http_router.dispatch_webui_mutation(
                    connection,
                    action,
                    payload,
                )
                status = response.status_code
                body = bytes(response.body).decode("utf-8", errors="replace").strip()
                if 200 <= status < 300:
                    try:
                        result = json.loads(body)
                    except json.JSONDecodeError:
                        return WebUIRequestResult(
                            status=502,
                            message="WebUI mutation returned an invalid response",
                        )
                    if action == "sidebar.update" and isinstance(result, dict):
                        await self.broadcast_webui_event(
                            "sidebar_state_updated",
                            state=result,
                        )
                    return WebUIRequestResult(result=result)
                return WebUIRequestResult(
                    status=status,
                    message=body or response.reason_phrase,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("WebUI mutation '{}' failed", action)
            return WebUIRequestResult(
                status=500,
                message="WebUI mutation failed",
            )

    async def send_webui_response(
        self,
        connection: ServerConnection,
        request_id: str,
        *,
        result: Any = None,
        status: int | None = None,
        message: str | None = None,
    ) -> None:
        if status is None:
            await self._transport.webui_send_event(
                connection,
                "webui_response",
                request_id=request_id,
                ok=True,
                result=result,
            )
            return
        await self._transport.webui_send_event(
            connection,
            "webui_response",
            request_id=request_id,
            ok=False,
            error={
                "status": status,
                "message": message or "WebUI mutation failed",
            },
        )

    async def close(self) -> None:
        """Cancel command work and release application-owned gateway state."""
        delivery_tasks = tuple(self.request_tasks.values())
        operation_tasks = tuple(operation.task for operation in self.request_operations.values())
        for task in (*delivery_tasks, *operation_tasks):
            task.cancel()
        if delivery_tasks:
            await asyncio.gather(*delivery_tasks, return_exceptions=True)
        if operation_tasks:
            await asyncio.gather(*operation_tasks, return_exceptions=True)
        self.request_tasks.clear()
        self.request_locks.clear()
        self.request_operations.clear()
        self.gateway.tokens.clear()
        self.gateway.endpoint.clear()
        self._temporary_chats.close()
