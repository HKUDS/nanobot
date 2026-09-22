"""Native Linear Agent channel runtime."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import ContextCompactionEvent, ProgressEvent, RetryWaitEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.linear.client import MAX_DOWNLOAD_BYTES, LinearApiError, LinearClient
from nanobot.channels.linear.config import LinearConfig
from nanobot.channels.linear.server import LinearServerLease, acquire_http_server
from nanobot.channels.linear.state import LinearStateStore, QueuedWebhook
from nanobot.config.paths import get_media_dir
from nanobot.security.network import validate_url_target
from nanobot.utils.helpers import safe_filename

MAX_PROMPT_ATTACHMENTS = 10


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
        event = msg.event
        if isinstance(event, ContextCompactionEvent):
            # Idle notifications have no originating Linear turn. Sending a thought
            # through the cached route would reactivate an already completed session.
            if _linear_route(msg.metadata) is None:
                return
            await self._create_activity(
                msg.chat_id,
                msg.metadata,
                {"type": "thought", "body": msg.content},
                key=f"compaction:{event.compaction_id}:{event.phase}",
                ephemeral=event.phase == "started",
            )
            return
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
        body = msg.content
        if msg.media:
            attachments = await self._attachment_markdown(msg)
            body = "\n\n".join(part for part in (body, *attachments) if part)
        if msg.buttons:
            options = [label.strip() for row in msg.buttons for label in row if label.strip()]
            if options:
                await self._create_activity(
                    msg.chat_id,
                    msg.metadata,
                    {"type": "elicitation", "body": body or "Choose an option."},
                    key="response:select",
                    signal="select",
                    signal_metadata={
                        "options": [{"label": label, "value": label} for label in options]
                    },
                )
                return
        if not body:
            return
        await self._create_activity(
            msg.chat_id,
            msg.metadata,
            {"type": "response", "body": body},
            key="response",
        )

    async def _attachment_markdown(self, msg: OutboundMessage) -> list[str]:
        client = self._client
        if client is None:
            raise RuntimeError("Linear HTTP client is not initialized")
        route = _linear_route(msg.metadata) or self._routes.get(msg.chat_id)
        if route is None:
            raise RuntimeError("Linear outbound message is missing route metadata")
        organization_id = _required_text(route, "organization_id")
        rendered: list[str] = []
        for media_ref in msg.media:
            parsed = urlparse(media_ref)
            try:
                if parsed.scheme in {"http", "https"}:
                    safe, error = await asyncio.to_thread(validate_url_target, media_ref)
                    if not safe:
                        raise LinearApiError(f"Unsafe attachment URL: {error}")
                    asset_url = media_ref
                    name = Path(parsed.path).name or "attachment"
                else:
                    path = Path(media_ref).expanduser()
                    asset_url = await client.upload_file(organization_id, path)
                    name = path.name or "attachment"
                label = _markdown_label(name)
                content_type = mimetypes.guess_type(name)[0] or ""
                prefix = "!" if content_type.startswith("image/") else ""
                rendered.append(f"{prefix}[{label}]({_markdown_target(asset_url)})")
            except (LinearApiError, OSError, ValueError):
                self.logger.exception("Failed to attach {} to Linear response", media_ref)
                rendered.append(f"[Unable to attach {_markdown_label(Path(media_ref).name)}]")
        return rendered

    async def send_reasoning_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        if not self.config.show_reasoning:
            return
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
        if body and self.config.show_reasoning:
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
        parameter = json.dumps(
            _redact_sensitive(arguments), ensure_ascii=False, default=str
        )[:2000]
        content: dict[str, Any] = {
            "type": "action",
            "action": _display_tool_name(name),
            "parameter": parameter,
        }
        if phase == "end":
            content["result"] = _compact_result(item.get("result"))
        elif phase == "error":
            content["result"] = _compact_result(item.get("error") or "Tool execution failed")
        await self._create_activity(
            msg.chat_id,
            msg.metadata,
            content,
            key=f"tool:{call_id}:{phase}",
            ephemeral=phase == "start",
        )

    async def _create_activity(
        self,
        chat_id: str,
        metadata: dict[str, Any],
        content: dict[str, Any],
        *,
        key: str,
        ephemeral: bool = False,
        signal: str | None = None,
        signal_metadata: dict[str, Any] | None = None,
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
            signal=signal,
            signal_metadata=signal_metadata,
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
        if signal == "stop":
            await self.bus.publish_inbound(
                InboundMessage(
                    channel=self.name,
                    sender_id=sender_id,
                    chat_id=agent_session_id,
                    content=content,
                    metadata=metadata,
                    session_key_override=f"linear:{organization_id}:{agent_session_id}",
                )
            )
            return
        media: list[str] = []
        if self.is_allowed(sender_id):
            media, attachment_warnings = await self._download_prompt_media(
                organization_id, content, delivery_id
            )
            if attachment_warnings:
                content = "\n\n".join((content, *attachment_warnings))
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
            media=media,
            metadata=metadata,
            session_key=f"linear:{organization_id}:{agent_session_id}",
            is_dm=True,
        )

    async def _download_prompt_media(
        self,
        organization_id: str,
        content: str,
        delivery_id: str,
    ) -> tuple[list[str], list[str]]:
        client = self._client
        if client is None:
            raise RuntimeError("Linear HTTP client is not initialized")
        labeled: dict[str, str] = {
            url: label.strip()
            for label, url in cast(
                list[tuple[str, str]], _LINEAR_MARKDOWN_UPLOAD_RE.findall(content)
            )
        }
        urls = list(dict.fromkeys(cast(list[str], _LINEAR_UPLOAD_URL_RE.findall(content))))
        warnings: list[str] = []
        if len(urls) > MAX_PROMPT_ATTACHMENTS:
            self.logger.warning(
                "Linear prompt {} contains {} attachments; processing the first {}",
                delivery_id,
                len(urls),
                MAX_PROMPT_ATTACHMENTS,
            )
            warnings.append(
                f"[Only the first {MAX_PROMPT_ATTACHMENTS} attachments were accepted.]"
            )
            urls = urls[:MAX_PROMPT_ATTACHMENTS]
        media: list[str] = []
        remaining_bytes = MAX_DOWNLOAD_BYTES
        for index, raw_url in enumerate(urls):
            if remaining_bytes <= 0:
                warnings.append("[Additional attachments were skipped: 40 MB total limit reached.]")
                break
            url = raw_url.rstrip(".,;:!?")
            try:
                body, content_type = await client.download_file(
                    organization_id, url, max_bytes=remaining_bytes
                )
                remaining_bytes -= len(body)
                name = _download_filename(url, labeled.get(url, ""), content_type, index)
                destination = get_media_dir("linear") / safe_filename(
                    f"{delivery_id}_{name}"
                )
                await asyncio.to_thread(destination.write_bytes, body)
                media.append(str(destination))
            except (LinearApiError, OSError, ValueError):
                self.logger.exception("Failed to download Linear attachment {}", url)
                label = labeled.get(url, "") or Path(urlparse(url).path).name or "attachment"
                warnings.append(f"[Attachment unavailable: {safe_filename(label)}]")
        return media, warnings

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
        with suppress(json.JSONDecodeError):
            parsed = cast(object, json.loads(value))
            if isinstance(parsed, dict | list):
                value = cast(object, parsed)
    value = _redact_sensitive(cast(object, value))
    if isinstance(value, str):
        return _redact_sensitive_text(value)[:2000]
    with suppress(TypeError, ValueError):
        return json.dumps(value, ensure_ascii=False, default=str)[:2000]
    return str(value)[:2000]


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)

_LINEAR_MARKDOWN_UPLOAD_RE = re.compile(
    r"!?\[([^\]]*)\]\((https://uploads\.linear\.app/[^)\s]+)\)"
)
_LINEAR_UPLOAD_URL_RE = re.compile(r"https://uploads\.linear\.app/[^\s<>\"')\]]+")
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)(\b(?:[a-z0-9]+[._-])*(?:api[._ -]?key|cookie|credential|password|secret|token)"
        r"\s*[:=]\s*)[^\s,;]+"
    ),
)


def _redact_sensitive(value: object) -> object:
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for raw_key, item in cast(dict[object, object], value).items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            redacted[key] = (
                "[redacted]"
                if any(part in normalized for part in _SENSITIVE_KEY_PARTS)
                else _redact_sensitive(item)
            )
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in cast(list[object], value)]
    if isinstance(value, tuple):
        return tuple(_redact_sensitive(item) for item in cast(tuple[object, ...], value))
    return value


def _redact_sensitive_text(value: str) -> str:
    for pattern in _SENSITIVE_TEXT_PATTERNS:
        value = pattern.sub(r"\1[redacted]", value)
    return value


def _display_tool_name(value: str) -> str:
    words = value.replace("-", " ").replace("_", " ").split()
    return " ".join(word.upper() if word.lower() in {"api", "mcp", "url"} else word.capitalize()
                    for word in words) or "Tool"


def _markdown_label(value: str) -> str:
    return (value or "attachment").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _markdown_target(value: str) -> str:
    return (
        value.replace("\\", "%5C")
        .replace(" ", "%20")
        .replace("(", "%28")
        .replace(")", "%29")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def _download_filename(url: str, label: str, content_type: str, index: int) -> str:
    candidate = safe_filename(Path(label).name) if label else ""
    if not candidate:
        candidate = safe_filename(Path(urlparse(url).path).name)
    if not candidate:
        candidate = f"attachment-{index + 1}"
    if not Path(candidate).suffix:
        candidate += mimetypes.guess_extension(content_type) or ".bin"
    return candidate[:180]
