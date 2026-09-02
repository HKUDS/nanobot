"""Slack channel implementation using Socket Mode."""

import asyncio
import re
from pathlib import Path
from typing import Any, Protocol, cast

import httpx
from pydantic import Field
from slack_sdk.socket_mode.async_client import AsyncBaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.websockets import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient
from slackify_markdown import slackify_markdown  # pyright: ignore[reportMissingTypeStubs]

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.pairing import is_approved
from nanobot.security.network import (
    PinnedDNSAsyncTransport,
    httpx_env_proxy_mounts,
    validate_url_target,
)
from nanobot.utils.helpers import safe_filename, split_message


def _as_json_object(value: Any) -> dict[str, Any] | None:
    """Narrow Slack's untyped Socket Mode payloads at the boundary."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _as_json_list(value: Any) -> list[Any] | None:
    """Narrow Slack's untyped Socket Mode arrays at the boundary."""
    return cast(list[Any], value) if isinstance(value, list) else None


class _SlackWebAPI(Protocol):
    """Subset of slack-sdk's dynamically typed Web API used by this channel."""

    async def auth_test(self, **kwargs: Any) -> Any: ...
    async def chat_postMessage(self, **kwargs: Any) -> Any: ...  # noqa: N802
    async def conversations_list(self, **kwargs: Any) -> Any: ...
    async def conversations_open(self, **kwargs: Any) -> Any: ...
    async def conversations_replies(self, **kwargs: Any) -> Any: ...
    async def files_upload_v2(self, **kwargs: Any) -> Any: ...
    async def reactions_add(self, **kwargs: Any) -> Any: ...
    async def reactions_remove(self, **kwargs: Any) -> Any: ...
    async def users_list(self, **kwargs: Any) -> Any: ...


class SlackDMConfig(Base):
    """Slack DM policy configuration."""

    enabled: bool = True
    policy: str = "open"
    allow_from: list[str] = Field(default_factory=list)


class SlackConfig(Base):
    """Slack channel configuration."""

    enabled: bool = False
    mode: str = "socket"
    webhook_path: str = "/slack/events"
    bot_token: str = ""
    app_token: str = ""
    reply_in_thread: bool = True
    react_emoji: str = "eyes"
    done_emoji: str = "white_check_mark"
    include_thread_context: bool = True
    thread_context_limit: int = 20
    allow_from: list[str] = Field(default_factory=list)
    group_policy: str = "mention"
    group_allow_from: list[str] = Field(default_factory=list)
    # When group_policy is "allowlist", also require the bot to be @mentioned
    # before responding (so it only replies to mentions in approved channels,
    # instead of every message). No effect for "mention"/"open" policies.
    group_require_mention: bool = False
    dm: SlackDMConfig = Field(default_factory=SlackDMConfig)


SLACK_MAX_MESSAGE_LEN = 39_000  # Slack API allows ~40k; leave margin
SLACK_DOWNLOAD_TIMEOUT = 30.0
# Abort Socket Mode WSS handshake after this many seconds. REST auth_test can still
# succeed while WSS blocks (firewall / region). slack-sdk does not apply HTTP(S)_PROXY
# to websockets.connect — see slack_sdk.socket_mode.websockets.SocketModeClient.connect.
SLACK_SOCKET_CONNECT_TIMEOUT_S = 45.0
_HTML_DOWNLOAD_PREFIXES = (b"<!doctype html", b"<html")


async def _validate_slack_download_request(request: httpx.Request) -> None:
    """Validate every Slack file request, including redirects, before transport."""
    ok, error = validate_url_target(str(request.url))
    if not ok:
        raise httpx.RequestError(f"unsafe Slack file URL: {error}", request=request)


class SlackChannel(BaseChannel):
    """Slack channel using Socket Mode."""

    name = "slack"
    display_name = "Slack"
    _SLACK_ID_RE = re.compile(r"^[CDGUW][A-Z0-9]{2,}$")
    _SLACK_CHANNEL_REF_RE = re.compile(r"^<#([A-Z0-9]+)(?:\|[^>]+)?>$")
    _SLACK_USER_REF_RE = re.compile(r"^<@([A-Z0-9]+)(?:\|[^>]+)?>$")

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return SlackConfig().model_dump(by_alias=True)

    _THREAD_CONTEXT_CACHE_LIMIT = 10_000

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = SlackConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: SlackConfig = config
        self._web_client: AsyncWebClient | None = None
        self._socket_client: SocketModeClient | None = None
        self._bot_user_id: str | None = None
        self._target_cache: dict[str, str] = {}
        self._thread_context_attempted: set[str] = set()

    def _require_web_api(self) -> _SlackWebAPI:
        if self._web_client is None:
            raise RuntimeError("Slack Web API client is not started")
        # slack-sdk's public methods are runtime-stable but its annotations do
        # not expose a useful shared interface, so narrow once at the SDK edge.
        return cast(_SlackWebAPI, self._web_client)

    async def start(self) -> None:
        """Start the Slack Socket Mode client."""
        if not self.config.bot_token or not self.config.app_token:
            self.logger.error("bot/app token not configured")
            return
        if self.config.mode != "socket":
            self.logger.error("Unsupported mode: {}", self.config.mode)
            return

        self._running = True

        self._web_client = AsyncWebClient(token=self.config.bot_token)
        self._socket_client = SocketModeClient(
            app_token=self.config.app_token,
            web_client=self._web_client,
        )

        self._socket_client.socket_mode_request_listeners.append(self._on_socket_request)

        # Resolve bot user ID for mention handling
        try:
            web_api = self._require_web_api()
            auth = await web_api.auth_test()
            self._bot_user_id = auth.get("user_id")
            self.logger.info("bot connected as {}", self._bot_user_id)
        except Exception as e:
            self.logger.warning("auth_test failed: {}", e)

        self.logger.info("Starting Socket Mode client...")
        try:
            await asyncio.wait_for(
                self._socket_client.connect(),
                timeout=SLACK_SOCKET_CONNECT_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            self.logger.error(
                "Slack Socket Mode WebSocket handshake timed out after {:.0f}s. "
                "auth_test uses HTTPS and may still succeed while WSS is blocked. "
                "Check outbound access to Slack WebSockets; slack-sdk Socket Mode "
                "does not apply HTTP(S)_PROXY to websockets.connect.",
                SLACK_SOCKET_CONNECT_TIMEOUT_S,
            )
            await self.stop()
            raise RuntimeError("Slack Socket Mode WebSocket connect timed out") from None

        self.logger.info("Slack Socket Mode WebSocket connected (events enabled)")

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Slack client."""
        self._running = False
        if self._socket_client:
            try:
                await self._socket_client.close()
            except Exception as e:
                self.logger.warning("socket close failed: {}", e)
            self._socket_client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Slack."""
        if not self._web_client:
            self.logger.warning("client not running")
            return
        try:
            web_api = self._require_web_api()
            target_chat_id = await self._resolve_target_chat_id(msg.chat_id)
            raw_slack_meta: Any = msg.metadata.get("slack", {}) if msg.metadata else {}
            slack_meta: dict[str, Any] = (
                cast(dict[str, Any], raw_slack_meta)
                if isinstance(raw_slack_meta, dict)
                else {}
            )
            thread_ts = slack_meta.get("thread_ts")
            event_meta = cast(dict[str, Any], slack_meta.get("event", {}) or {})
            origin_chat_id = str(event_meta.get("channel") or msg.chat_id)
            # Reply in the same thread the inbound message belongs to (works
            # for both real channel threads and DM threads). When the agent
            # is forwarding to a different channel, drop thread_ts because it
            # only makes sense within the originating conversation.
            thread_ts_param = thread_ts if thread_ts and target_chat_id == origin_chat_id else None

            is_progress = isinstance(msg.event, ProgressEvent)
            if is_progress and not msg.content:
                pass  # skip empty progress messages (e.g. tool-event-only updates)
            elif msg.content or not (msg.media or []):
                mrkdwn = self._to_mrkdwn(msg.content) if msg.content else " "
                raw_buttons = getattr(msg, "buttons", None)
                buttons: list[list[str]] = (
                    cast(list[list[str]], raw_buttons)
                    if isinstance(raw_buttons, list)
                    and all(
                        isinstance(row, list)
                        and all(
                            isinstance(label, str)
                            for label in cast(list[object], row)
                        )
                        for row in cast(list[object], raw_buttons)
                    )
                    else []
                )
                chunks = split_message(mrkdwn, SLACK_MAX_MESSAGE_LEN)
                for index, chunk in enumerate(chunks):
                    kwargs: dict[str, Any] = dict(
                        channel=target_chat_id, text=chunk, thread_ts=thread_ts_param,
                    )
                    if buttons and index == len(chunks) - 1:
                        kwargs["blocks"] = self._build_button_blocks(chunk, buttons)
                    await web_api.chat_postMessage(**kwargs)

            for media_path in msg.media or []:
                try:
                    await web_api.files_upload_v2(
                        channel=target_chat_id,
                        file=media_path,
                        thread_ts=thread_ts_param,
                    )
                except Exception:
                    self.logger.exception("Failed to upload file {}", media_path)

            # Update reaction emoji when the final (non-progress) response is sent
            if not is_progress:
                raw_event = slack_meta.get("event", {})
                event = (
                    cast(dict[str, Any], raw_event)
                    if isinstance(raw_event, dict)
                    else {}
                )
                await self._update_react_emoji(
                    origin_chat_id,
                    cast(str | None, event.get("ts")),
                )

        except Exception:
            self.logger.exception("Error sending message")
            raise

    async def _resolve_target_chat_id(self, target: str) -> str:
        """Resolve human-friendly Slack targets to concrete IDs when needed."""
        if not self._web_client:
            return target

        target = target.strip()
        if not target:
            return target

        if match := self._SLACK_CHANNEL_REF_RE.fullmatch(target):
            return match.group(1)
        if match := self._SLACK_USER_REF_RE.fullmatch(target):
            return await self._open_dm_for_user(match.group(1))
        if self._SLACK_ID_RE.fullmatch(target):
            if target.startswith(("U", "W")):
                return await self._open_dm_for_user(target)
            return target

        if target.startswith("#"):
            return await self._resolve_channel_name(target[1:])
        if target.startswith("@"):
            return await self._resolve_user_handle(target[1:])

        try:
            return await self._resolve_channel_name(target)
        except ValueError:
            return await self._resolve_user_handle(target)

    async def _resolve_channel_name(self, name: str) -> str:
        normalized = self._normalize_target_name(name)
        if not normalized:
            raise ValueError("Slack target channel name is empty")

        cache_key = f"channel:{normalized}"
        if cache_key in self._target_cache:
            return self._target_cache[cache_key]

        cursor: str | None = None
        web_api = self._require_web_api()
        while True:
            response = cast(dict[str, Any], await web_api.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            ))
            for channel_value in cast(list[object], response.get("channels", [])):
                channel = cast(dict[str, Any], channel_value)
                if self._normalize_target_name(str(channel.get("name") or "")) == normalized:
                    channel_id = str(channel.get("id") or "")
                    if channel_id:
                        self._target_cache[cache_key] = channel_id
                        return channel_id
            response_metadata = cast(
                dict[str, Any],
                response.get("response_metadata") or {},
            )
            cursor = str(response_metadata.get("next_cursor") or "").strip()
            if not cursor:
                break

        raise ValueError(
            f"Slack channel '{name}' was not found. Use a joined channel name like "
            f"'#general' or a concrete channel ID."
        )

    async def _resolve_user_handle(self, handle: str) -> str:
        normalized = self._normalize_target_name(handle)
        if not normalized:
            raise ValueError("Slack target user handle is empty")

        cache_key = f"user:{normalized}"
        if cache_key in self._target_cache:
            return self._target_cache[cache_key]

        cursor: str | None = None
        web_api = self._require_web_api()
        while True:
            response = cast(
                dict[str, Any],
                await web_api.users_list(limit=200, cursor=cursor),
            )
            for member_value in cast(list[object], response.get("members", [])):
                member = cast(dict[str, Any], member_value)
                if self._member_matches_handle(member, normalized):
                    user_id = str(member.get("id") or "")
                    if not user_id:
                        continue
                    dm_id = await self._open_dm_for_user(user_id)
                    self._target_cache[cache_key] = dm_id
                    return dm_id
            response_metadata = cast(
                dict[str, Any],
                response.get("response_metadata") or {},
            )
            cursor = str(response_metadata.get("next_cursor") or "").strip()
            if not cursor:
                break

        raise ValueError(
            f"Slack user '{handle}' was not found. Use '@name' or a concrete DM/channel ID."
        )

    async def _open_dm_for_user(self, user_id: str) -> str:
        web_api = self._require_web_api()
        response = cast(
            dict[str, Any],
            await web_api.conversations_open(users=user_id),
        )
        channel = cast(dict[str, Any], response.get("channel") or {})
        channel_id = str(channel.get("id") or "")
        if not channel_id:
            raise ValueError(f"Slack DM target for user '{user_id}' could not be opened.")
        return channel_id

    @staticmethod
    def _normalize_target_name(value: str) -> str:
        return value.strip().lstrip("#@").lower()

    @classmethod
    def _member_matches_handle(cls, member: dict[str, Any], normalized: str) -> bool:
        profile = cast(dict[str, Any], member.get("profile") or {})
        candidates = {
            str(member.get("name") or ""),
            str(profile.get("display_name") or ""),
            str(profile.get("display_name_normalized") or ""),
            str(profile.get("real_name") or ""),
            str(profile.get("real_name_normalized") or ""),
        }
        return normalized in {cls._normalize_target_name(candidate) for candidate in candidates if candidate}

    async def _on_socket_request(
        self,
        client: AsyncBaseSocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        """Handle incoming Socket Mode requests."""
        if req.type == "interactive":
            await self._on_block_action(client, req)
            return
        if req.type != "events_api":
            return

        # Acknowledge right away
        await client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )

        payload = _as_json_object(cast(Any, req).payload) or {}
        event = _as_json_object(payload.get("event")) or {}
        event_type = event.get("type")

        # Handle app mentions or plain messages
        if event_type not in ("message", "app_mention"):
            return

        sender_id = event.get("user")
        chat_id = event.get("channel")

        subtype = event.get("subtype")
        # Slack uses subtype=file_share for user messages with attachments.
        # Ignore other subtypes such as bot_message / message_changed / deleted.
        if subtype and subtype != "file_share":
            return
        if self._bot_user_id and sender_id == self._bot_user_id:
            return

        # Avoid double-processing: Slack sends both `message` and `app_mention`
        # for mentions in channels. Prefer `app_mention`.
        text = event.get("text") or ""
        if not isinstance(text, str):
            return
        if event_type == "message" and self._bot_user_id and f"<@{self._bot_user_id}>" in text:
            return

        # Debug: log basic event shape
        self.logger.debug(
            "event: type={} subtype={} user={} channel={} channel_type={} text={}",
            event_type,
            subtype,
            sender_id,
            chat_id,
            event.get("channel_type"),
            text[:80],
        )
        if not isinstance(sender_id, str) or not sender_id or not isinstance(chat_id, str) or not chat_id:
            return

        channel_type = event.get("channel_type") or ""
        if not isinstance(channel_type, str):
            channel_type = ""

        if not self._is_allowed(sender_id, chat_id, channel_type):
            if channel_type == "im" and self.config.dm.enabled:
                await self._handle_message(
                    sender_id=sender_id,
                    chat_id=chat_id,
                    content="",
                    is_dm=True,
                )
            return

        if channel_type != "im" and not self._should_respond_in_channel(event_type, text, chat_id):
            return

        text = self._strip_bot_mention(text)

        event_ts = event.get("ts")
        event_ts = event_ts if isinstance(event_ts, str) else None
        raw_thread_ts = event.get("thread_ts")
        raw_thread_ts = raw_thread_ts if isinstance(raw_thread_ts, str) else None
        thread_ts = raw_thread_ts
        # In DMs we don't auto-open a thread on top-level messages (it would
        # bury replies under "1 reply"). But if the user explicitly opened a
        # thread inside the DM, raw_thread_ts is set and we honor it.
        if (
            self.config.reply_in_thread
            and not thread_ts
            and channel_type != "im"
        ):
            thread_ts = event_ts
        # Add :eyes: reaction to the triggering message (best-effort)
        try:
            if self._web_client and event_ts:
                web_api = self._require_web_api()
                await web_api.reactions_add(
                    channel=chat_id,
                    name=self.config.react_emoji,
                    timestamp=event_ts,
                )
        except Exception as e:
            self.logger.debug("reactions_add failed: {}", e)

        # Thread-scoped session key whenever the turn lives in a thread: either the
        # message arrived inside one (raw_thread_ts) or reply_in_thread opens a new
        # thread for this channel message. DM roots have no thread_ts and keep the
        # default per-chat session, so context doesn't bleed across thread boundaries.
        session_key = f"slack:{chat_id}:{thread_ts}" if thread_ts else None
        media_paths: list[str] = []
        file_markers: list[str] = []
        for file_info in _as_json_list(event.get("files")) or []:
            file_info_object = _as_json_object(file_info)
            if file_info_object is None:
                continue
            file_path, marker = await self._download_slack_file(file_info_object)
            if file_path:
                media_paths.append(file_path)
            if marker:
                file_markers.append(marker)

        is_slash = text.strip().startswith("/")
        content = text if is_slash else await self._with_thread_context(
            text,
            chat_id=chat_id,
            channel_type=channel_type,
            thread_ts=thread_ts,
            raw_thread_ts=raw_thread_ts,
            current_ts=event_ts,
        )
        if file_markers:
            content = "\n".join(part for part in [content, *file_markers] if part)
        if not content and not media_paths:
            return

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media_paths,
                metadata={
                    "slack": {
                        "event": event,
                        "thread_ts": thread_ts,
                        "channel_type": channel_type,
                    },
                },
                session_key=session_key,
            )
        except Exception:
            self.logger.exception("Error handling message from {}", sender_id)

    async def _download_slack_file(self, file_info: dict[str, Any]) -> tuple[str | None, str]:
        """Download a Slack private file to the local media directory."""
        file_id = str(file_info.get("id") or "file")
        name = str(
            file_info.get("name")
            or file_info.get("title")
            or file_info.get("id")
            or "slack-file"
        )
        marker_type = "image" if str(file_info.get("mimetype") or "").startswith("image/") else "file"
        marker = f"[{marker_type}: {name}]"
        url = str(file_info.get("url_private_download") or file_info.get("url_private") or "")
        if not url:
            return None, self._download_failure_marker(marker_type, name, "missing download url")
        if not self.config.bot_token:
            return None, self._download_failure_marker(marker_type, name, "missing bot token")

        filename = safe_filename(f"{file_id}_{name}")
        path = Path(get_media_dir("slack")) / filename
        try:
            async with httpx.AsyncClient(
                timeout=SLACK_DOWNLOAD_TIMEOUT,
                follow_redirects=True,
                transport=PinnedDNSAsyncTransport(),
                mounts=httpx_env_proxy_mounts(),
                event_hooks={"request": [_validate_slack_download_request]},
            ) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.config.bot_token}"},
                )
                response.raise_for_status()
            if self._looks_like_html_download(response):
                raise ValueError("Slack returned HTML instead of file content")
            path.write_bytes(response.content)
            return str(path), marker
        except Exception as e:
            self.logger.warning("Failed to download file {}: {}", file_id, e)
            return None, self._download_failure_marker(marker_type, name, "download failed")

    @staticmethod
    def _download_failure_marker(marker_type: str, name: str, reason: str) -> str:
        return (
            f"[{marker_type}: {name}: {reason}; not available to nanobot. "
            "Check Slack files:read scope, reinstall the Slack app, and ensure the bot can access the file.]"
        )

    @staticmethod
    def _looks_like_html_download(response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type:
            return True
        preview = response.content[:256].lstrip().lower()
        return preview.startswith(_HTML_DOWNLOAD_PREFIXES)

    async def _on_block_action(
        self,
        client: AsyncBaseSocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        """Handle button clicks from inline action buttons."""
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        payload = cast(dict[str, Any], cast(Any, req).payload or {})
        actions = cast(list[Any], payload.get("actions") or [])
        if not actions:
            return
        action = cast(dict[str, Any], actions[0])
        value = str(action.get("value") or "")
        user_info = cast(dict[str, Any], payload.get("user") or {})
        sender_id = str(user_info.get("id") or "")
        channel_info = cast(dict[str, Any], payload.get("channel") or {})
        chat_id = str(channel_info.get("id") or "")
        if not sender_id or not chat_id or not value:
            return
        message_info = cast(dict[str, Any], payload.get("message") or {})
        thread_ts = cast(
            str | None,
            message_info.get("thread_ts") or message_info.get("ts"),
        )
        channel_type = self._infer_channel_type(chat_id)
        if not self._is_allowed(sender_id, chat_id, channel_type):
            return
        session_key = f"slack:{chat_id}:{thread_ts}" if thread_ts else None
        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=value,
                metadata={"slack": {"thread_ts": thread_ts, "channel_type": channel_type}},
                session_key=session_key,
            )
        except Exception:
            self.logger.exception("Error handling button click from {}", sender_id)

    async def _with_thread_context(
        self,
        text: str,
        *,
        chat_id: str,
        channel_type: str,
        thread_ts: str | None,
        raw_thread_ts: str | None,
        current_ts: str | None,
    ) -> str:
        """Include thread history the first time the bot is pulled into a Slack thread."""
        del channel_type  # DM and channel threads are both fetched via conversations.replies
        if (
            not self.config.include_thread_context
            or not self._web_client
            or not raw_thread_ts
            or not thread_ts
            or current_ts == thread_ts
        ):
            return text

        key = f"{chat_id}:{thread_ts}"
        if key in self._thread_context_attempted:
            return text
        if len(self._thread_context_attempted) >= self._THREAD_CONTEXT_CACHE_LIMIT:
            self._thread_context_attempted.clear()
        self._thread_context_attempted.add(key)

        try:
            web_api = self._require_web_api()
            response = cast(dict[str, Any], await web_api.conversations_replies(
                channel=chat_id,
                ts=thread_ts,
                limit=max(1, self.config.thread_context_limit),
            ))
        except Exception as e:
            self.logger.warning("thread context unavailable for {}: {}", key, e)
            return text

        lines = self._format_thread_context(
            cast(list[dict[str, Any]], response.get("messages", [])),
            current_ts=current_ts,
        )
        if not lines:
            return text
        return "Slack thread context before this mention:\n" + "\n".join(lines) + f"\n\nCurrent message:\n{text}"

    def _format_thread_context(self, messages: list[dict[str, Any]], *, current_ts: str | None) -> list[str]:
        lines: list[str] = []
        for item in messages:
            if item.get("ts") == current_ts:
                continue
            if item.get("subtype"):
                continue
            sender = str(item.get("user") or item.get("bot_id") or "unknown")
            is_bot = self._bot_user_id is not None and sender == self._bot_user_id
            label = "bot" if is_bot else f"<@{sender}>"
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            text = self._strip_bot_mention(text)
            if len(text) > 500:
                text = text[:500] + "…"
            lines.append(f"- {label}: {text}")
        return lines

    @staticmethod
    def _build_button_blocks(text: str, buttons: list[list[str]]) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks with action buttons."""
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}},
        ]
        elements: list[dict[str, Any]] = []
        for row in buttons:
            for label in row:
                elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": label[:75]},
                    "value": label[:75],
                    "action_id": f"btn_{label[:50]}",
                })
        if elements:
            blocks.append({"type": "actions", "elements": elements[:25]})
        return blocks

    async def _update_react_emoji(self, chat_id: str, ts: str | None) -> None:
        """Remove the in-progress reaction and optionally add a done reaction."""
        if not self._web_client or not ts:
            return
        web_api = self._require_web_api()
        try:
            await web_api.reactions_remove(
                channel=chat_id,
                name=self.config.react_emoji,
                timestamp=ts,
            )
        except Exception as e:
            self.logger.debug("reactions_remove failed: {}", e)
        if self.config.done_emoji:
            try:
                await web_api.reactions_add(
                    channel=chat_id,
                    name=self.config.done_emoji,
                    timestamp=ts,
                )
            except Exception as e:
                self.logger.debug("done reaction failed: {}", e)

    def _is_allowed(self, sender_id: str, chat_id: str, channel_type: str) -> bool:
        if channel_type == "im":
            if not self.config.dm.enabled:
                return False
            if self.config.dm.policy == "allowlist":
                return sender_id in self.config.dm.allow_from or is_approved(self.name, sender_id)
            return True

        # Group / channel messages
        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return True

    def _is_mention(self, event_type: str, text: str) -> bool:
        if event_type == "app_mention":
            return True
        return self._bot_user_id is not None and f"<@{self._bot_user_id}>" in text

    def _should_respond_in_channel(self, event_type: str, text: str, chat_id: str) -> bool:
        if self.config.group_policy == "open":
            return True
        if self.config.group_policy == "mention":
            return self._is_mention(event_type, text)
        if self.config.group_policy == "allowlist":
            if chat_id not in self.config.group_allow_from:
                return False
            if self.config.group_require_mention:
                return self._is_mention(event_type, text)
            return True
        return False

    def is_allowed(self, sender_id: str) -> bool:
        # Slack needs channel-aware policy checks, so _on_socket_request and
        # _on_block_action call _is_allowed before handing off to BaseChannel.
        return True

    @staticmethod
    def _infer_channel_type(chat_id: str) -> str:
        if chat_id.startswith("D"):
            return "im"
        if chat_id.startswith("G"):
            return "group"
        return "channel"

    def _strip_bot_mention(self, text: str) -> str:
        if not text or not self._bot_user_id:
            return text
        return re.sub(rf"<@{re.escape(self._bot_user_id)}>\s*", "", text).strip()

    _TABLE_RE = re.compile(r"(?m)^\|.*\|$(?:\n\|[\s:|-]*\|$)(?:\n\|.*\|$)*")
    _CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
    _INLINE_CODE_RE = re.compile(r"`[^`]+`")
    _LEFTOVER_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
    _LEFTOVER_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
    _BARE_URL_RE = re.compile(r"(?<![|<])(https?://\S+)")

    @classmethod
    def _to_mrkdwn(cls, text: str) -> str:
        """Convert Markdown to Slack mrkdwn, including tables."""
        if not text:
            return ""
        code_blocks: list[str] = []

        def _save_fence(m: re.Match[str]) -> str:
            code_blocks.append(m.group(0))
            return f"\x00CB{len(code_blocks) - 1}\x00"

        text = cls._CODE_FENCE_RE.sub(_save_fence, text)
        text = cls._TABLE_RE.sub(cls._convert_table, text)
        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CB{i}\x00", block)
        return cls._fixup_mrkdwn(slackify_markdown(text)).rstrip("\n")

    @classmethod
    def _fixup_mrkdwn(cls, text: str) -> str:
        """Fix markdown artifacts that slackify_markdown misses."""
        code_blocks: list[str] = []

        def _save_code(m: re.Match[str]) -> str:
            code_blocks.append(m.group(0))
            return f"\x00CB{len(code_blocks) - 1}\x00"

        text = cls._CODE_FENCE_RE.sub(_save_code, text)
        text = cls._INLINE_CODE_RE.sub(_save_code, text)
        text = cls._LEFTOVER_BOLD_RE.sub(r"*\1*", text)
        text = cls._LEFTOVER_HEADER_RE.sub(r"*\1*", text)
        text = cls._BARE_URL_RE.sub(
            lambda m: m.group(0).replace("&amp;", "&"),
            text,
        )

        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CB{i}\x00", block)
        return text

    @staticmethod
    def _convert_table(match: re.Match[str]) -> str:
        """Convert a Markdown table to a Slack-readable list."""
        lines = [ln.strip() for ln in match.group(0).strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            return match.group(0)
        headers = [h.strip() for h in lines[0].strip("|").split("|")]
        start = 2 if re.fullmatch(r"[|\s:\-]+", lines[1]) else 1
        rows: list[str] = []
        for line in lines[start:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            cells = (cells + [""] * len(headers))[: len(headers)]
            parts = [f"**{headers[i]}**: {cells[i]}" for i in range(len(headers)) if cells[i]]
            if parts:
                rows.append(" · ".join(parts))
        return "\n".join(rows)
