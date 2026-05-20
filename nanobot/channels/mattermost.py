"""Mattermost channel implementation using WebSocket for inbound events and REST for outbound messages."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

import httpx
import websockets
from httpx import HTTPStatusError
from loguru import logger
from pydantic import Field

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import Base

MATTERMOST_API_PREFIX = "/api/v4"
_RECONNECT_DELAY_S = 5


class MattermostDMConfig(Base):
    """Mattermost DM policy configuration."""

    enabled: bool = True
    policy: Literal["open", "allowlist"] = "open"
    allow_from: list[str] = Field(default_factory=list)


class MattermostConfig(Base):
    """Mattermost channel configuration."""

    enabled: bool = False
    server_url: str = ""
    token: str = ""
    react_emoji_name: str = "star-struck"
    allow_from: list[str] = Field(default_factory=list)
    allow_from_match_mode: Literal["id", "username", "email"] = "id"
    group_policy: Literal["mention", "open", "allowlist"] = "mention"
    group_allow_from: list[str] = Field(default_factory=list)
    reply_in_thread: bool = True
    dm: MattermostDMConfig = Field(default_factory=MattermostDMConfig)


class MattermostChannel(BaseChannel):
    """Mattermost channel using WebSocket inbound events and REST API outbound sends."""

    name = "mattermost"
    display_name = "Mattermost"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MattermostConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = MattermostConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: MattermostConfig = config
        self._client: httpx.AsyncClient | None = None
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._bot_user_id: str | None = None
        self._bot_username: str | None = None
        self._channel_types: dict[str, str] = {}
        self._usernames: dict[str, str] = {}
        self._user_emails: dict[str, str] = {}

    async def start(self) -> None:
        """Start the Mattermost channel and listen for websocket events."""
        if not self.config.server_url or not self.config.token:
            logger.error("Mattermost server URL or token not configured")
            return

        self._running = True
        created_client = False
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
            created_client = True

        try:
            await self._load_bot_identity()
        except Exception as e:
            logger.error("Mattermost auth check failed: {}", e)
            self._running = False
            if created_client and self._client:
                await self._client.aclose()
                self._client = None
            return

        ws_url = self._websocket_url()
        headers = self._headers()

        while self._running:
            try:
                logger.info("Connecting to Mattermost websocket...")
                async with websockets.connect(ws_url, additional_headers=headers) as ws:
                    self._ws = ws
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._handle_websocket_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("Mattermost websocket error: {}", e)
                if self._running:
                    await asyncio.sleep(_RECONNECT_DELAY_S)
            finally:
                self._ws = None

    async def stop(self) -> None:
        """Stop the Mattermost channel and close resources."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Mattermost REST API."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)

        mattermost_meta = (msg.metadata or {}).get("mattermost", {})
        file_ids = await self._upload_files(msg.chat_id, msg.media or [])
        payload: dict[str, Any] = {
            "channel_id": msg.chat_id,
            "message": msg.content,
        }
        if file_ids:
            payload["file_ids"] = file_ids
        root_id = mattermost_meta.get("root_id")
        if self.config.reply_in_thread and root_id:
            payload["root_id"] = root_id
        if not payload.get("message") and not payload.get("file_ids"):
            return

        response = await self._client.post(
            self._api_url("/posts"),
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()

    async def _handle_websocket_message(self, raw: str) -> None:
        """Parse a raw websocket message and dispatch supported events."""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Ignoring invalid Mattermost websocket payload: {}", raw)
            return

        if payload.get("event") != "posted":
            return

        await self._handle_posted_event(payload.get("data") or {}, payload.get("broadcast") or {})

    async def _handle_posted_event(self, data: dict[str, Any], broadcast: dict[str, Any]) -> None:
        """Handle a Mattermost posted websocket event."""
        raw_post = data.get("post")
        if not raw_post:
            return

        try:
            post = json.loads(raw_post) if isinstance(raw_post, str) else raw_post
        except json.JSONDecodeError:
            logger.debug("Ignoring Mattermost posted event with invalid post JSON")
            return

        if not isinstance(post, dict):
            logger.debug("Ignoring Mattermost posted event with non-object post payload")
            return

        user_id = str(post.get("user_id") or "")
        chat_id = str(post.get("channel_id") or broadcast.get("channel_id") or "")
        content = post.get("message") or ""
        post_id = str(post.get("id") or "")
        root_id = str(post.get("root_id") or "") or None
        team_id = str(post.get("team_id") or broadcast.get("team_id") or "") or None

        if not user_id or not chat_id:
            return
        if self._bot_user_id and user_id == self._bot_user_id:
            return

        try:
            channel_type = await self._get_channel_type(chat_id, data)
        except Exception as e:
            logger.warning("Mattermost channel type lookup failed for {}: {}", chat_id, e)
            return

        if self._is_dm_channel(channel_type):
            if not await self._is_dm_allowed(user_id):
                return
        else:
            if not self._should_respond_in_channel(chat_id, content):
                return

        if not await self._is_sender_allowed(user_id):
            return

        sender_id = await self._build_sender_id(user_id, data, post)
        clean_content = self._strip_bot_mention(content)
        session_key = None
        if self.config.reply_in_thread and not self._is_dm_channel(channel_type):
            session_key = f"mattermost:{chat_id}:{root_id or post_id}"

        await self._add_reaction(post_id)

        await self.bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                sender_id=str(sender_id),
                chat_id=str(chat_id),
                content=clean_content,
                metadata={
                    "mattermost": {
                        "post_id": post_id,
                        "root_id": root_id,
                        "channel_type": channel_type,
                        "team_id": team_id,
                    }
                },
                session_key_override=session_key,
            )
        )

    def is_allowed(self, sender_id: str) -> bool:
        """Apply synchronous allow checks used by BaseChannel."""
        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list:
            return False
        if "*" in allow_list:
            return True

        mode = self.config.allow_from_match_mode
        sender_str = str(sender_id)
        user_id, username = self._parse_sender_identity(sender_str)

        if mode == "id":
            return user_id in allow_list if user_id else sender_str in allow_list
        if mode == "username":
            return bool(username and username in allow_list)
        if mode == "email":
            if not user_id:
                return False
            email = self._user_emails.get(user_id)
            normalized_allow = {value.lower() for value in allow_list}
            return bool(email and email.lower() in normalized_allow)
        return False

    async def _load_bot_identity(self) -> None:
        """Load the authenticated bot user identity."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)

        response = await self._client.get(self._api_url("/users/me"), headers=self._headers())
        response.raise_for_status()
        user = response.json()
        if not isinstance(user, dict):
            raise ValueError("Mattermost /users/me returned non-object JSON")
        self._bot_user_id = str(user.get("id") or "") or None
        self._bot_username = user.get("username") or None
        if self._bot_user_id and self._bot_username:
            self._usernames[self._bot_user_id] = self._bot_username
            email = user.get("email")
            if email:
                self._user_emails[self._bot_user_id] = str(email).lower()

    async def _build_sender_id(
        self, user_id: str, event_data: dict[str, Any], post: dict[str, Any]
    ) -> str:
        """Build a sender identifier that prefers id|username when possible."""
        username = self._extract_event_username(event_data, post)
        if not username:
            try:
                username = await self._get_username(user_id)
            except Exception as e:
                logger.debug("Mattermost username lookup failed for {}: {}", user_id, e)
                username = None
        return f"{user_id}|{username}" if username else user_id

    def _extract_event_username(self, event_data: dict[str, Any], post: dict[str, Any]) -> str | None:
        """Extract username from event payloads when present."""
        for key in ("sender_name", "username"):
            value = event_data.get(key)
            if isinstance(value, str) and value:
                return value
        for key in ("username",):
            value = post.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    async def _get_username(self, user_id: str) -> str | None:
        """Resolve and cache Mattermost username for a user ID."""
        identity = await self._get_user_identity(user_id)
        return identity.get("username")

    async def _get_user_identity(self, user_id: str) -> dict[str, str | None]:
        """Resolve and cache Mattermost identity fields for a user ID."""
        cached_username = self._usernames.get(user_id)
        cached_email = self._user_emails.get(user_id)
        if cached_username is not None or cached_email is not None:
            return {"username": cached_username, "email": cached_email}

        identity = await self._fetch_user_identity(user_id)
        username = identity.get("username")
        email = identity.get("email")
        if username:
            self._usernames[user_id] = username
        if email:
            self._user_emails[user_id] = email
        return identity

    async def _fetch_user_identity(self, user_id: str) -> dict[str, str | None]:
        """Fetch a Mattermost username and email by user ID."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)
        response = await self._client.get(
            self._api_url(f"/users/{user_id}"),
            headers=self._headers(),
        )
        response.raise_for_status()
        user = response.json()
        if not isinstance(user, dict):
            raise ValueError("Mattermost /users/{user_id} returned non-object JSON")
        username = user.get("username")
        email = user.get("email")
        return {
            "username": str(username) if username else None,
            "email": str(email).lower() if email else None,
        }

    async def _get_channel_type(self, channel_id: str, event_data: dict[str, Any]) -> str:
        """Resolve and cache Mattermost channel type."""
        direct = event_data.get("channel_type")
        if isinstance(direct, str) and direct:
            self._channel_types[channel_id] = direct
            return direct
        cached = self._channel_types.get(channel_id)
        if cached:
            return cached
        fetched = await self._fetch_channel_type(channel_id)
        self._channel_types[channel_id] = fetched
        return fetched

    async def _fetch_channel_type(self, channel_id: str) -> str:
        """Fetch channel metadata from Mattermost REST API."""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)
        response = await self._client.get(
            self._api_url(f"/channels/{channel_id}"),
            headers=self._headers(),
        )
        response.raise_for_status()
        channel = response.json()
        if not isinstance(channel, dict):
            raise ValueError("Mattermost /channels/{channel_id} returned non-object JSON")
        return str(channel.get("type") or "")

    async def _upload_files(self, channel_id: str, media_paths: list[str]) -> list[str]:
        """Upload files to Mattermost and return their IDs."""
        if not media_paths:
            return []
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)

        with ExitStack() as stack:
            files: list[tuple[str, tuple[str, Any, str]]] = []
            for media_path in media_paths:
                path = Path(media_path)
                if not path.is_file():
                    raise FileNotFoundError(f"Mattermost file not found: {media_path}")
                handle = stack.enter_context(path.open("rb"))
                files.append(("files", (path.name, handle, "application/octet-stream")))

            response = await self._client.post(
                self._api_url("/files"),
                headers=self._headers(),
                data={"channel_id": channel_id},
                files=files,
            )
        response.raise_for_status()
        payload = response.json()
        file_infos = payload.get("file_infos") or []
        return [str(info.get("id")) for info in file_infos if info.get("id")]

    async def _add_reaction(self, post_id: str) -> None:
        """Add emoji reaction to an inbound post (best-effort)."""
        if not post_id or not self.config.react_emoji_name or not self._bot_user_id:
            return
        if not self._client:
            self._client = httpx.AsyncClient(timeout=30.0)

        try:
            response = await self._client.post(
                self._api_url("/reactions"),
                headers=self._headers(),
                json={
                    "user_id": self._bot_user_id,
                    "post_id": post_id,
                    "emoji_name": self.config.react_emoji_name,
                },
            )
            response.raise_for_status()
        except HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 400:
                logger.debug(
                    "Mattermost reaction already exists or invalid for post {} (emoji={}): {}",
                    post_id,
                    self.config.react_emoji_name,
                    status,
                )
            else:
                logger.warning(
                    "Mattermost reaction add failed for post {} (emoji={}): status={}",
                    post_id,
                    self.config.react_emoji_name,
                    status,
                )
        except Exception as e:
            logger.warning(
                "Mattermost reaction add failed for post {} (emoji={}): {}",
                post_id,
                self.config.react_emoji_name,
                e,
            )

    def _headers(self) -> dict[str, str]:
        """Return authentication headers for Mattermost REST and websocket requests."""
        return {"Authorization": f"Bearer {self.config.token}"}

    def _api_url(self, path: str) -> str:
        """Build a Mattermost REST API URL."""
        return f"{self.config.server_url.rstrip('/')}{MATTERMOST_API_PREFIX}{path}"

    def _websocket_url(self) -> str:
        """Build the Mattermost websocket URL from server_url."""
        parsed = urlparse(self.config.server_url.rstrip("/"))
        scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_path = f"{parsed.path.rstrip('/')}{MATTERMOST_API_PREFIX}/websocket"
        return urlunparse((scheme, parsed.netloc, ws_path, "", "", ""))

    def _is_dm_channel(self, channel_type: str) -> bool:
        """Return True for direct-message channels."""
        return channel_type == "D"

    async def _is_dm_allowed(self, user_id: str) -> bool:
        """Check DM policy before global allow_from filtering."""
        if not self.config.dm.enabled:
            return False
        if self.config.dm.policy != "allowlist":
            return True
        return await self._matches_allow_list(user_id, self.config.dm.allow_from)

    async def _is_sender_allowed(self, user_id: str) -> bool:
        """Check global sender allow_from policy."""
        return await self._matches_allow_list(user_id, self.config.allow_from)

    async def _matches_allow_list(self, user_id: str, allow_list: list[str]) -> bool:
        """Match a Mattermost sender against the configured allowlist mode."""
        if not allow_list:
            return False
        if "*" in allow_list:
            return True

        mode = self.config.allow_from_match_mode
        if mode == "id":
            return user_id in allow_list

        try:
            identity = await self._get_user_identity(user_id)
        except Exception as e:
            logger.debug("Mattermost identity lookup failed for {}: {}", user_id, e)
            return False

        if mode == "username":
            username = identity.get("username")
            return bool(username and username in allow_list)
        if mode == "email":
            email = identity.get("email")
            normalized_allow = {value.lower() for value in allow_list}
            return bool(email and email.lower() in normalized_allow)
        return False

    def _should_respond_in_channel(self, chat_id: str, text: str) -> bool:
        """Check whether a group/channel message should trigger the bot."""
        if self.config.group_policy == "open":
            return True
        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        if self.config.group_policy == "mention":
            if not self._bot_username:
                return False
            return f"@{self._bot_username}" in text
        return False

    def _parse_sender_identity(self, sender_id: str) -> tuple[str | None, str | None]:
        """Parse the internal sender identity string."""
        if sender_id.count("|") != 1:
            return (sender_id or None, None)
        user_id, username = sender_id.split("|", 1)
        if not user_id or not username:
            return (None, None)
        return user_id, username

    def _strip_bot_mention(self, text: str) -> str:
        """Remove Mattermost @username mentions directed at the bot."""
        if not text or not self._bot_username:
            return text
        pattern = rf"(?<!\w)@{re.escape(self._bot_username)}\b[:,]?\s*"
        return re.sub(pattern, "", text).strip()
