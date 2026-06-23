"""Mattermost channel implementation using WebSocket + REST API."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config_base import Base
from nanobot.pairing import PAIRING_CODE_META_KEY, format_pairing_reply, generate_code
from nanobot.utils.helpers import safe_filename, split_message

MATTERMOST_MAX_MESSAGE_LEN = 16383
MATTERMOST_WS_RECONNECT_BASE_DELAY = 1
MATTERMOST_WS_RECONNECT_MAX_DELAY = 30

_CHANNEL_TYPES = {
    "O": "public",
    "P": "private",
    "D": "dm",
    "G": "group",
}


class MattermostDMConfig(Base):
    """Mattermost DM policy configuration."""
    enabled: bool = True
    policy: str = "open"
    allow_from: list[str] = Field(default_factory=list)


class MattermostConfig(Base):
    """Mattermost channel configuration."""
    enabled: bool = False
    server_url: str = ""
    token: str = ""
    team_id: str = ""
    allow_from_match_mode: str = "id"
    allow_from: list[str] = Field(default_factory=list)
    group_policy: str = "mention"
    group_allow_from: list[str] = Field(default_factory=list)
    reply_in_thread: bool = True
    include_thread_context: bool = True
    thread_context_limit: int = 20
    streaming: bool = True
    streaming_max_chars: int = 16000
    react_emoji: str = "eyes"
    done_emoji: str = "white_check_mark"
    send_progress: bool = True
    send_tool_hints: bool = False
    dm: MattermostDMConfig = Field(default_factory=MattermostDMConfig)


def _server_url_to_ws_url(server_url: str) -> str:
    if server_url.startswith("https://"):
        return server_url.replace("https://", "wss://", 1) + "/api/v4/websocket"
    if server_url.startswith("http://"):
        return server_url.replace("http://", "ws://", 1) + "/api/v4/websocket"
    return server_url + "/api/v4/websocket"


class MattermostChannel(BaseChannel):
    """Mattermost channel using WebSocket + REST API."""

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
        self._server_url = config.server_url.rstrip("/")
        self._ws_url = _server_url_to_ws_url(self._server_url)
        self._http_client: httpx.AsyncClient | None = None
        self._ws_task: asyncio.Task | None = None
        self._self_id: str | None = None
        self._self_username: str | None = None
        self._self_email: str | None = None
        self._usernames: dict[str, str] = {}
        self._user_emails: dict[str, str] = {}
        self._channel_types: dict[str, str] = {}
        self._stream_posts: dict[str, str] = {}
        self._stream_buffers: dict[str, str] = {}
        self._stream_last_content: dict[str, str] = {}
        self._stream_committed: dict[str, str] = {}
        self._stream_root_ids: dict[str, str] = {}
        self._thread_context_attempted: set[str] = set()

    # Lifecycle ----------------------------------------------------------------

    async def start(self) -> None:
        if not self.config.server_url or not self.config.token:
            self.logger.error("serverUrl and token must be configured")
            return

        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self._server_url,
                headers={"Authorization": f"Bearer {self.config.token}"},
                timeout=30.0,
            )

        try:
            resp = await self._http_client.get("/api/v4/users/me")
            resp.raise_for_status()
            me = resp.json()
            self._self_id = me.get("id")
            self._self_username = me.get("username")
            self._self_email = me.get("email", "")
            self.logger.info("bot @{} connected", self._self_username)
        except Exception as e:
            self.logger.error("Failed to identify bot user: {}", e)
            await self._cleanup_http()
            return

        self._running = True
        self._ws_task = asyncio.create_task(self._ws_listen_loop())

    async def stop(self) -> None:
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
        await self._cleanup_http()

    async def _cleanup_http(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    # WebSocket ----------------------------------------------------------------

    async def _ws_listen_loop(self) -> None:
        import websockets

        delay = MATTERMOST_WS_RECONNECT_BASE_DELAY
        while self._running:
            try:
                async with websockets.connect(
                    self._ws_url,
                    additional_headers={"Authorization": f"Bearer {self.config.token}"},
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    self.logger.debug("websocket connected")
                    delay = MATTERMOST_WS_RECONNECT_BASE_DELAY
                    async for raw in ws:
                        await self._handle_ws_message(json.loads(raw))
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                self.logger.warning("websocket error: {} (reconnect in {}s)", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, MATTERMOST_WS_RECONNECT_MAX_DELAY)

    async def _handle_ws_message(self, msg: dict[str, Any]) -> None:
        event = msg.get("event", "")
        if event == "posted":
            await self._handle_posted_event(msg)
        elif event == "action":
            await self._handle_action_event(msg)
        elif event == "post_deleted":
            await self._handle_post_deleted_event(msg)

    # Event: posted ------------------------------------------------------------

    async def _handle_posted_event(self, msg: dict[str, Any]) -> None:
        data = msg.get("data", {})
        broadcast = msg.get("broadcast", {})

        raw_post = data.get("post", "{}")
        try:
            post = json.loads(raw_post) if isinstance(raw_post, str) else raw_post
        except json.JSONDecodeError:
            self.logger.warning("failed to parse post json")
            return

        sender_id = post.get("user_id", "")
        channel_id = post.get("channel_id", "")
        message_text = post.get("message", "")
        root_id = post.get("root_id", "") or ""
        post_id = post.get("id", "")
        file_ids: list[str] = post.get("file_ids", [])

        if self._self_id and sender_id == self._self_id:
            return
        if not sender_id or not channel_id:
            return

        channel_type_code = data.get("channel_type", "")
        channel_type = _CHANNEL_TYPES.get(channel_type_code, "public")
        is_dm = channel_type == "dm"

        team_id = broadcast.get("team_id", "")
        if self.config.team_id and team_id and team_id != self.config.team_id:
            if not is_dm:
                return

        if not await self._is_allowed(sender_id, channel_id, channel_type):
            if is_dm and self.config.dm.enabled:
                code = generate_code(self.name, str(sender_id))
                await self.send(
                    OutboundMessage(
                        channel=self.name,
                        chat_id=str(channel_id),
                        content=format_pairing_reply(code),
                        metadata={PAIRING_CODE_META_KEY: code},
                    )
                )
                self.logger.info(
                    "Sent pairing code {} to sender {} in chat {}",
                    code, sender_id, channel_id,
                )
            return

        if not is_dm and not self._should_respond_in_channel(message_text, channel_id):
            return

        message_text = self._strip_bot_mention(message_text)

        thread_ts = root_id if root_id else None
        if self.config.reply_in_thread and not thread_ts and not is_dm:
            thread_ts = post_id
        session_key = (
            f"mattermost:{channel_id}:{thread_ts}" if thread_ts and root_id else None
        )

        try:
            await self._add_reaction(channel_id, post_id, self.config.react_emoji)
        except Exception:
            self.logger.debug("add reaction failed")

        media_paths: list[str] = []
        for fid in file_ids:
            path = await self._download_file(fid)
            if path:
                media_paths.append(path)

        content = message_text
        if root_id and self.config.include_thread_context:
            content = await self._with_thread_context(
                content, channel_id=channel_id, root_id=root_id,
            )

        mm_meta: dict[str, Any] = {
            "post_id": post_id,
            "root_id": root_id,
            "channel_type": channel_type,
        }
        if thread_ts:
            mm_meta["thread_ts"] = thread_ts

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content=content,
            media=media_paths,
            metadata={
                "mattermost": mm_meta,
                "message_id": post_id,
            },
            session_key=session_key,
            is_dm=is_dm,
        )

    # Event: action ------------------------------------------------------------

    async def _handle_action_event(self, msg: dict[str, Any]) -> None:
        data = msg.get("data", {})
        sender_id = data.get("user_id", "")
        channel_id = data.get("channel_id", "")
        context = data.get("context", {}) or {}
        value = context.get("selected_option", "")

        if not sender_id or not channel_id or not value:
            return

        channel_type = await self.resolve_channel_type(channel_id)
        if not await self._is_allowed(sender_id, channel_id, channel_type):
            return

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content=value,
            metadata={"mattermost": {"channel_type": channel_type, "is_action": True}},
        )

    # Event: post_deleted ------------------------------------------------------

    async def _handle_post_deleted_event(self, msg: dict[str, Any]) -> None:
        data = msg.get("data", {})
        raw_post = data.get("post", "{}")
        try:
            post = json.loads(raw_post) if isinstance(raw_post, str) else raw_post
        except json.JSONDecodeError:
            return
        post_id = post.get("id", "")
        if not post_id:
            return
        to_remove = [sid for sid, pid in self._stream_posts.items() if pid == post_id]
        for sid in to_remove:
            self._stream_posts.pop(sid, None)
            self._stream_buffers.pop(sid, None)
            self._stream_last_content.pop(sid, None)
            self._stream_committed.pop(sid, None)

    # Permission / policy ------------------------------------------------------

    def is_allowed(self, sender_id: str) -> bool:
        return True

    async def _is_allowed(self, sender_id: str, chat_id: str, channel_type: str) -> bool:
        if channel_type == "dm":
            if not self.config.dm.enabled:
                return False
            if self.config.dm.policy == "allowlist":
                return await self._match_sender(sender_id, self.config.dm.allow_from)
            return True

        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return True

    def _should_respond_in_channel(self, text: str, chat_id: str) -> bool:
        if self.config.group_policy == "open":
            return True
        if self.config.group_policy == "mention":
            return self._is_mentioned(text)
        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return False

    _BOT_MENTION_RE: re.Pattern | None = None

    def _is_mentioned(self, text: str) -> bool:
        if not self._self_username:
            return False
        if self._BOT_MENTION_RE is None:
            pat = r"(?<![@\w])@" + re.escape(self._self_username) + r"(?![@\w])"
            self._BOT_MENTION_RE = re.compile(pat)
        return bool(self._BOT_MENTION_RE.search(text))

    def _strip_bot_mention(self, text: str) -> str:
        if not text or not self._self_username:
            return text
        return re.sub(rf"@{re.escape(self._self_username)}\s*", "", text).strip()

    async def _match_sender(self, sender_id: str, allow_list: list[str]) -> bool:
        if not allow_list:
            return False
        if "*" in allow_list:
            return True
        mode = self.config.allow_from_match_mode
        if mode == "id":
            return sender_id in allow_list
        if mode == "username":
            username = await self._resolve_username(sender_id)
            return username in allow_list if username else False
        if mode == "email":
            email = await self._resolve_email(sender_id)
            return email in allow_list if email else False
        return False

    async def _resolve_username(self, user_id: str) -> str | None:
        if user_id in self._usernames:
            return self._usernames[user_id]
        try:
            user = await self._api_get(f"/api/v4/users/{user_id}")
            self._usernames[user_id] = user.get("username", "")
            return self._usernames[user_id]
        except Exception as e:
            self.logger.warning("failed to resolve username for {}: {}", user_id, e)
            return None

    async def _resolve_email(self, user_id: str) -> str | None:
        if user_id in self._user_emails:
            return self._user_emails[user_id]
        try:
            user = await self._api_get(f"/api/v4/users/{user_id}")
            self._user_emails[user_id] = user.get("email", "").lower()
            return self._user_emails[user_id]
        except Exception as e:
            self.logger.warning("failed to resolve email for {}: {}", user_id, e)
            return None

    # Thread context -----------------------------------------------------------

    async def _with_thread_context(self, text: str, *, channel_id: str, root_id: str) -> str:
        key = f"{channel_id}:{root_id}"
        if key in self._thread_context_attempted:
            return text
        self._thread_context_attempted.add(key)

        try:
            data = await self._api_get(
                f"/api/v4/posts/{root_id}/thread?perPage={max(1, self.config.thread_context_limit)}",
            )
        except Exception as e:
            self.logger.warning("thread context unavailable for {}: {}", key, e)
            return text

        posts = data.get("posts", {})
        order = data.get("order", [])
        if not order:
            return text

        lines: list[str] = []
        for pid in order:
            post = posts.get(pid, {})
            if post.get("id") == root_id:
                continue
            if post.get("user_id") == self._self_id:
                label = "bot"
            else:
                label = f"<{post.get('user_id', 'unknown')}>"
            msg_text = (post.get("message", "") or "").strip()
            if not msg_text:
                continue
            if len(msg_text) > 500:
                msg_text = msg_text[:500] + "\u2026"
            lines.append(f"- {label}: {msg_text}")

        if not lines:
            return text
        return "Mattermost thread context before this mention:\n" + "\n".join(lines) + f"\n\nCurrent message:\n{text}"

    # Send ---------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        if not self._http_client:
            self.logger.warning("client not initialized")
            return

        try:
            chat_id = msg.chat_id
            meta = msg.metadata or {}
            mm_meta = meta.get("mattermost", {}) or {}
            root_id = mm_meta.get("root_id") or mm_meta.get("thread_ts") or meta.get("root_id")

            file_ids: list[str] = []
            for media_path in msg.media or []:
                try:
                    fid = await self._upload_file(chat_id, media_path)
                    if fid:
                        file_ids.append(fid)
                except Exception:
                    self.logger.exception("Failed to upload file {}", media_path)

            if msg.content or file_ids:
                text = msg.content or " "
                chunks = split_message(text, MATTERMOST_MAX_MESSAGE_LEN)
                for i, chunk in enumerate(chunks):
                    await self._create_post(
                        chat_id, chunk,
                        root_id=root_id if self.config.reply_in_thread else None,
                        file_ids=(file_ids if i == 0 else None) or None,
                    )

            if not meta.get("_progress") and meta.get("message_id"):
                try:
                    await self._remove_reaction(meta["message_id"], self.config.react_emoji)
                except Exception:
                    self.logger.debug("remove reaction failed")
                if self.config.done_emoji:
                    try:
                        await self._add_reaction(chat_id, meta["message_id"], self.config.done_emoji)
                    except Exception:
                        self.logger.debug("done reaction failed")

        except Exception:
            self.logger.exception("Error sending message")
            raise

    # Streaming -----------------------------------------------------------------

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        if not self._http_client:
            return

        meta = metadata or {}
        stream_id = meta.get("_stream_id", chat_id)

        if meta.get("_stream_end"):
            stream_root = self._stream_root_ids.pop(stream_id, None)
            self._stream_posts.pop(stream_id, None)
            self._stream_last_content.pop(stream_id, None)
            buf = self._stream_buffers.pop(stream_id, None)
            final = self._stream_committed.pop(stream_id, None) or buf

            if not meta.get("_progress") and meta.get("message_id"):
                try:
                    await self._remove_reaction(meta["message_id"], self.config.react_emoji)
                except Exception:
                    self.logger.debug("remove reaction failed")

            if final and not meta.get("_progress") and not meta.get("_resuming"):
                try:
                    mm_meta = (meta.get("mattermost", {}) or {}) if isinstance(meta.get("mattermost"), dict) else {}
                    root_id = mm_meta.get("root_id") or mm_meta.get("thread_ts") or meta.get("root_id") or stream_root
                    chunks = split_message(final, MATTERMOST_MAX_MESSAGE_LEN)
                    for i, chunk in enumerate(chunks):
                        post = await self._create_post(
                            chat_id, chunk,
                            root_id=root_id if self.config.reply_in_thread else None,
                        )
                        if i == 0 and self.config.done_emoji:
                            try:
                                await self._add_reaction(chat_id, post["id"], self.config.done_emoji)
                            except Exception:
                                self.logger.debug("done reaction failed")
                except Exception:
                    self.logger.exception("stream final post failed")
            return

        if not delta.strip():
            return

        committed = self._stream_committed.get(stream_id, "")
        buf = committed + delta
        self._stream_buffers[stream_id] = buf
        self._stream_committed[stream_id] = buf
        return

    # API helpers ---------------------------------------------------------------

    async def _api_get(self, path: str) -> dict[str, Any]:
        resp = await self._http_client.get(path)
        resp.raise_for_status()
        return resp.json()

    async def _api_post(self, path: str, json_data: dict[str, Any]) -> dict[str, Any]:
        resp = await self._http_client.post(path, json=json_data)
        resp.raise_for_status()
        return resp.json()

    async def _api_put(self, path: str, json_data: dict[str, Any]) -> dict[str, Any]:
        resp = await self._http_client.put(path, json=json_data)
        resp.raise_for_status()
        return resp.json()

    async def _create_post(
        self,
        channel_id: str,
        message: str,
        *,
        root_id: str | None = None,
        file_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "channel_id": channel_id,
            "message": message,
        }
        if root_id:
            body["root_id"] = root_id
        if file_ids:
            body["file_ids"] = file_ids
        return await self._api_post("/api/v4/posts", body)

    async def _edit_post(self, post_id: str, message: str) -> dict[str, Any]:
        return await self._api_put(f"/api/v4/posts/{post_id}", {"id": post_id, "message": message})

    async def _upload_file(self, channel_id: str, file_path: str) -> str | None:
        path = Path(file_path)
        if not path.exists():
            self.logger.warning("file not found: {}", file_path)
            return None

        try:
            files = {"files": (path.name, path.read_bytes())}
            resp = await self._http_client.post(
                "/api/v4/files",
                data={"channel_id": channel_id},
                files=files,
            )
            resp.raise_for_status()
            data = resp.json()
            infos = data.get("file_infos", [])
            if infos:
                return infos[0].get("id")
        except Exception as e:
            self.logger.warning("file upload failed for {}: {}", file_path, e)
        return None

    async def _download_file(self, file_id: str) -> str | None:
        try:
            info_resp = await self._http_client.get(f"/api/v4/files/{file_id}/info")
            info_resp.raise_for_status()
            info = info_resp.json()
            name = Path(info.get("name", file_id)).name
            out = Path(get_media_dir("mattermost")) / safe_filename(f"{file_id}_{name}")
            out.parent.mkdir(parents=True, exist_ok=True)

            dl = await self._http_client.get(f"/api/v4/files/{file_id}")
            dl.raise_for_status()
            out.write_bytes(dl.content)
            return str(out)
        except Exception as e:
            self.logger.warning("file download failed for {}: {}", file_id, e)
            return None

    async def _add_reaction(self, channel_id: str, post_id: str, emoji: str) -> None:
        if not self._self_id or not emoji:
            return
        await self._api_post("/api/v4/reactions", {
            "user_id": self._self_id,
            "post_id": post_id,
            "emoji_name": emoji,
        })

    async def _remove_reaction(self, post_id: str, emoji: str) -> None:
        if not self._self_id or not emoji:
            return
        resp = await self._http_client.delete(
            f"/api/v4/users/{self._self_id}/posts/{post_id}/reactions/{emoji}",
        )
        if resp.status_code >= 400:
            self.logger.debug("remove reaction failed: {} {}", resp.status_code, resp.text)

    async def resolve_channel_type(self, channel_id: str) -> str:
        if channel_id in self._channel_types:
            return self._channel_types[channel_id]
        try:
            data = await self._api_get(f"/api/v4/channels/{channel_id}")
            ctype = _CHANNEL_TYPES.get(data.get("type", ""), "public")
            self._channel_types[channel_id] = ctype
            return ctype
        except Exception:
            return "public"
