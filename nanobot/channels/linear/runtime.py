"""Native Linear Agent channel runtime."""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from typing import Any, cast

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent, RetryWaitEvent, outbound_event_from_message
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.linear.client import LinearApiError, LinearClient
from nanobot.channels.linear.config import LinearConfig
from nanobot.channels.linear.server import LinearServerLease, acquire_http_server
from nanobot.channels.linear.state import LinearStateStore, QueuedWebhook


class LinearPayloadError(ValueError):
    """A signed webhook has an unsupported or malformed payload."""


class LinearChannel(BaseChannel):
    """Receive @mention Agent Sessions and publish native Agent Activities."""

    name = "linear"
    display_name = "Linear"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return LinearConfig().model_dump(mode="json", by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = LinearConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: LinearConfig = config
        self._state = LinearStateStore()
        self._client: LinearClient | None = None
        self._server: LinearServerLease | None = None
        self._reasoning: dict[tuple[str, str], list[str]] = {}
        self._routes: dict[str, dict[str, Any]] = {}

    def progress_transport_defaults(self) -> tuple[bool, bool] | None:
        return self.config.send_progress, self.config.send_tool_hints

    async def start(self) -> None:
        self.config.validate_runtime()
        if not self._state.has_installations(self.config.client_id):
            raise RuntimeError("Connect at least one Linear workspace with OAuth before enabling")
        self._state.recover_processing_webhooks()
        self._client = LinearClient(self.config, self._state)
        try:
            self._server = await asyncio.to_thread(
                acquire_http_server,
                self.config,
                self._state,
            )
        except Exception:
            await self._client.close()
            self._client = None
            raise
        self._running = True
        self.logger.info(
            "Linear webhook listening on http://{}:{}{} (public URL: {})",
            self.config.host,
            self.config.port,
            self.config.webhook_path,
            self.config.webhook_url,
        )
        while self._running:
            events = await asyncio.to_thread(self._state.claim_webhooks)
            if not events:
                await asyncio.sleep(0.2)
                continue
            for event in events:
                await self._process_queued_webhook(event)

    async def stop(self) -> None:
        self._running = False
        if self._server is not None:
            await asyncio.to_thread(self._server.close)
            self._server = None
        if self._client is not None:
            await self._client.close()
            self._client = None
        self._reasoning.clear()
        self._routes.clear()

    def start_error_message(self, error: Exception) -> str | None:
        return f"Linear channel failed to start: {error}"

    async def send(self, msg: OutboundMessage) -> None:
        event = outbound_event_from_message(msg)
        if isinstance(event, ProgressEvent):
            if event.tool_events:
                for item in event.tool_events:
                    await self._send_tool_event(msg, item)
                return
            if msg.content:
                await self._create_activity(
                    msg.chat_id,
                    msg.metadata,
                    {"type": "thought", "body": msg.content},
                    key=f"progress:{hash(msg.content)}",
                    ephemeral=True,
                )
            return
        if isinstance(event, RetryWaitEvent):
            await self._create_activity(
                msg.chat_id,
                msg.metadata,
                {"type": "thought", "body": msg.content},
                key=f"retry:{hash(msg.content)}",
                ephemeral=True,
            )
            return
        if not msg.content:
            return
        await self._create_activity(
            msg.chat_id,
            msg.metadata,
            {"type": "response", "body": msg.content},
            key="response",
        )

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        key = (chat_id, stream_id or "default")
        self._reasoning.setdefault(key, []).append(delta)

    async def send_reasoning_end(
        self,
        chat_id: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        key = (chat_id, stream_id or "default")
        body = "".join(self._reasoning.pop(key, [])).strip()
        if body:
            await self._create_activity(
                chat_id,
                metadata or {},
                {"type": "thought", "body": body},
                key=f"reasoning:{stream_id or 'default'}",
            )

    async def send_file_edit_events(
        self,
        chat_id: str,
        edits: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        for index, edit in enumerate(edits):
            path = str(edit.get("path") or edit.get("file") or "file")
            result = str(edit.get("status") or edit.get("phase") or "updated")
            await self._create_activity(
                chat_id,
                metadata or {},
                {
                    "type": "action",
                    "action": "Edit file",
                    "parameter": path,
                    "result": result,
                },
                key=f"file:{path}:{index}:{result}",
            )

    async def _send_tool_event(self, msg: OutboundMessage, item: dict[str, Any]) -> None:
        name = str(item.get("name") or "tool")
        phase = str(item.get("phase") or "start")
        call_id = str(item.get("call_id") or uuid.uuid4())
        arguments = item.get("arguments")
        parameter = json.dumps(arguments, ensure_ascii=False, default=str)[:2000]
        content: dict[str, Any] = {
            "type": "action",
            "action": name,
            "parameter": parameter,
        }
        if phase == "end":
            content["result"] = _compact_result(item.get("result"))
        elif phase == "error":
            content["result"] = str(item.get("error") or "Tool execution failed")
        await self._create_activity(
            msg.chat_id,
            msg.metadata,
            content,
            key=f"tool:{call_id}:{phase}",
        )

    async def _create_activity(
        self,
        chat_id: str,
        metadata: dict[str, Any],
        content: dict[str, Any],
        *,
        key: str,
        ephemeral: bool = False,
    ) -> None:
        client = self._client
        if client is None:
            raise RuntimeError("Linear HTTP client is not initialized")
        route = _linear_route(metadata) or self._routes.get(chat_id)
        if route is None:
            raise RuntimeError("Linear outbound message is missing route metadata")
        metadata.setdefault("linear", route)
        session_id = str(route.get("agent_session_id") or chat_id)
        organization_id = _required_text(route, "organization_id")
        activity_ids_raw = metadata.setdefault("_linear_activity_ids", {})
        if not isinstance(activity_ids_raw, dict):
            activity_ids_raw = {}
            metadata["_linear_activity_ids"] = activity_ids_raw
        activity_ids = cast(dict[str, Any], activity_ids_raw)
        activity_id = str(activity_ids.setdefault(key, str(uuid.uuid4())))
        await client.create_activity(
            organization_id,
            session_id,
            content,
            activity_id=activity_id,
            ephemeral=ephemeral,
        )

    async def _process_queued_webhook(self, event: QueuedWebhook) -> None:
        try:
            await self._process_webhook(event.delivery_id, event.payload)
        except LinearPayloadError as exc:
            self.logger.warning("Dropping invalid Linear webhook {}: {}", event.delivery_id, exc)
            await asyncio.to_thread(self._state.complete_webhook, event.delivery_id)
        except LinearApiError as exc:
            self.logger.warning("Linear webhook {} failed: {}", event.delivery_id, exc)
            if exc.retryable:
                await asyncio.to_thread(
                    self._state.retry_webhook,
                    event.delivery_id,
                    str(exc),
                    event.attempts,
                    exc.retry_after,
                )
            else:
                await asyncio.to_thread(self._state.complete_webhook, event.delivery_id)
        except Exception as exc:
            self.logger.exception("Linear webhook {} failed", event.delivery_id)
            await asyncio.to_thread(
                self._state.retry_webhook,
                event.delivery_id,
                str(exc),
                event.attempts,
            )
        else:
            await asyncio.to_thread(self._state.complete_webhook, event.delivery_id)

    async def _process_webhook(self, delivery_id: str, payload: dict[str, Any]) -> None:
        event_type = payload.get("type")
        if event_type in {"OAuthApp", "OAuthAuthorization", "PermissionChange"}:
            self._process_lifecycle_event(payload)
            return
        if event_type != "AgentSessionEvent":
            raise LinearPayloadError("unsupported event type")
        action = _required_text(payload, "action")
        if action not in {"created", "prompted"}:
            return
        session = _required_object(payload, "agentSession")
        agent_session_id = _required_text(session, "id")
        organization_id = _required_text(payload, "organizationId")
        if str(session.get("organizationId") or organization_id) != organization_id:
            raise LinearPayloadError("organization mismatch")
        installation = self._state.installation(organization_id)
        if installation is None:
            raise LinearPayloadError("organization is not installed")
        activity = _optional_object(payload.get("agentActivity"))
        if activity and str(activity.get("userId") or "") == installation.app_user_id:
            return
        signal = str(activity.get("signal") or "") if activity else ""
        sender_id = str(
            (activity or {}).get("userId")
            or session.get("creatorId")
            or ""
        ).strip()
        if not sender_id:
            raise LinearPayloadError("missing sender identity")
        content = "/stop" if signal == "stop" else _prompt_text(payload, session, activity, action)
        if not content:
            if signal in {"auth", "continue", "select"}:
                content = _signal_text(signal, activity)
            if not content:
                return
        metadata = {
            "message_id": delivery_id,
            "linear": {
                "organization_id": organization_id,
                "agent_session_id": agent_session_id,
                "issue_id": str(session.get("issueId") or ""),
                "comment_id": str(session.get("commentId") or ""),
                "app_user_id": installation.app_user_id,
                "oauth_client_id": str(payload.get("oauthClientId") or ""),
                "action": action,
                "signal": signal,
                "delivery_id": delivery_id,
            },
        }
        self._routes[agent_session_id] = cast(dict[str, Any], metadata["linear"])
        if len(self._routes) > 1000:
            self._routes.pop(next(iter(self._routes)))
        await self._create_activity(
            agent_session_id,
            metadata,
            {"type": "thought", "body": "Starting…"},
            key="accepted",
            ephemeral=True,
        )
        await self._handle_message(
            sender_id=sender_id,
            chat_id=agent_session_id,
            content=content,
            metadata=metadata,
            session_key=f"linear:{organization_id}:{agent_session_id}",
            is_dm=True,
        )

    def _process_lifecycle_event(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "").lower()
        organization_id = str(payload.get("organizationId") or "").strip()
        if organization_id and action in {"remove", "removed", "revoke", "revoked"}:
            self._state.delete_installation(organization_id)
            self.logger.info("Removed revoked Linear workspace installation {}", organization_id)


def _linear_route(metadata: dict[str, Any]) -> dict[str, Any] | None:
    value = metadata.get("linear")
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise LinearPayloadError(f"missing {key}")
    return item.strip()


def _required_object(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise LinearPayloadError(f"missing {key}")
    return cast(dict[str, Any], item)


def _optional_object(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _prompt_text(
    payload: dict[str, Any],
    session: dict[str, Any],
    activity: dict[str, Any],
    action: str,
) -> str:
    value: object
    if action == "created":
        value = payload.get("promptContext")
    else:
        value = activity.get("body") or activity.get("content")
    return _text_from_value(value) or _text_from_value(session.get("comment"))


def _text_from_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        for key in ("body", "text", "prompt", "content"):
            text = _text_from_value(mapping.get(key))
            if text:
                return text
    if isinstance(value, list):
        parts = [_text_from_value(item) for item in cast(list[object], value)]
        return "\n".join(part for part in parts if part)
    return ""


def _signal_text(signal: str, activity: dict[str, Any]) -> str:
    metadata = activity.get("signalMetadata")
    text = _text_from_value(metadata)
    return text or f"Linear agent signal: {signal}"


def _compact_result(value: object) -> str:
    if isinstance(value, str):
        return value[:2000]
    with suppress(TypeError, ValueError):
        return json.dumps(value, ensure_ascii=False, default=str)[:2000]
    return str(value)[:2000]
