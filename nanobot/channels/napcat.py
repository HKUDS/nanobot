"""NapCat channel implementation using OneBot 11 over WebSocket."""

import asyncio
import base64
import json
import mimetypes
from collections import OrderedDict
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import websockets
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base


class NapCatConfig(Base):
    """NapCat OneBot WebSocket channel configuration."""

    enabled: bool = False
    ws_url: str = "ws://127.0.0.1:3001/"
    access_token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "mention"] = "mention"
    reconnect_delay_s: float = 5.0
    handle_notice_events: bool = False
    handle_request_events: bool = False
    message_debounce_enabled: bool = True
    message_debounce_seconds: float = 5.0
    message_debounce_max_messages: int = 5


class NapCatChannel(BaseChannel):
    """NapCat channel using OneBot 11 forward WebSocket."""

    name = "napcat"
    display_name = "NapCat (QQ)"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return NapCatConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = NapCatConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: NapCatConfig = config
        self._ws: Any = None
        self._self_id: str | None = None
        self._chat_type_cache: dict[str, str] = {}
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._echo_counter = 0
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._http: httpx.AsyncClient | None = None
        self._message_buffer: dict[str, list[dict[str, Any]]] = {}
        self._debounce_timers: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start the NapCat forward WebSocket client."""
        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

        while self._running:
            try:
                await self._run_connection()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("NapCat websocket error: {}", e)
                self._pending_responses.clear()
            finally:
                self._ws = None

            if self._running:
                logger.info("Reconnecting NapCat in {}s...", self.config.reconnect_delay_s)
                await asyncio.sleep(self.config.reconnect_delay_s)

        if self._http:
            await self._http.aclose()
            self._http = None

    async def stop(self) -> None:
        """Stop the NapCat channel."""
        self._running = False
        self._pending_responses.clear()

        for task in self._debounce_timers.values():
            if not task.done():
                task.cancel()
        self._debounce_timers.clear()
        self._message_buffer.clear()

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send text and optional media via OneBot actions."""
        if not self._ws:
            logger.warning("NapCat websocket not connected")
            return

        is_group = bool(
            msg.metadata.get("is_group")
            if msg.metadata
            else self._chat_type_cache.get(msg.chat_id) == "group"
        )

        if msg.media:
            await self._send_message_with_media(msg.chat_id, msg.content or "", msg.media, is_group)
            return

        if msg.content:
            await self._send_text(msg.chat_id, msg.content, is_group)

    async def _run_connection(self) -> None:
        """Open the websocket and process inbound events until disconnect."""
        headers = self._connect_headers()
        async with websockets.connect(self.config.ws_url, additional_headers=headers or None) as ws:
            self._ws = ws
            logger.info("NapCat websocket connected to {}", self.config.ws_url)
            message_task = asyncio.create_task(self._recv_loop(ws))
            try:
                login = await self._call_api("get_login_info")
                if isinstance(login, dict) and login.get("user_id") is not None:
                    self._self_id = str(login["user_id"])
                await message_task
            finally:
                if not message_task.done():
                    message_task.cancel()
                    try:
                        await message_task
                    except asyncio.CancelledError:
                        pass

    async def _recv_loop(self, ws: Any) -> None:
        """Consume websocket frames so API responses can resolve concurrently."""
        async for raw in ws:
            await self._handle_ws_message(raw)

    def _connect_headers(self) -> dict[str, str]:
        """Build websocket auth headers."""
        if not self.config.access_token:
            return {}
        return {"Authorization": f"Bearer {self.config.access_token}"}

    async def _send_text(self, chat_id: str, content: str, is_group: bool) -> None:
        """Send one text message."""
        action = "send_group_msg" if is_group else "send_private_msg"
        target_key = "group_id" if is_group else "user_id"
        result = await self._call_api(action, {target_key: int(chat_id), "message": content})
        if result is None:
            logger.warning("NapCat text send failed to {}", chat_id)

    async def _send_media(self, chat_id: str, media_path: str, is_group: bool) -> None:
        """Send one media message using OneBot segment arrays."""
        segment = await self._build_media_segment(media_path)
        if segment is None:
            return

        action = "send_group_msg" if is_group else "send_private_msg"
        target_key = "group_id" if is_group else "user_id"
        result = await self._call_api(
            action,
            {
                target_key: int(chat_id),
                "message": [segment],
            },
        )
        if result is None:
            logger.warning("NapCat {} send failed to {}", segment["type"], chat_id)

    async def _send_message_with_media(self, chat_id: str, content: str, media_paths: list[str], is_group: bool) -> None:
        """Send one combined OneBot message containing optional text and media segments."""
        segments: list[dict[str, Any]] = []
        if content:
            segments.append({"type": "text", "data": {"text": content}})
        for media_path in media_paths:
            segment = await self._build_media_segment(media_path)
            if segment is not None:
                segments.append(segment)
        if not segments:
            return

        action = "send_group_msg" if is_group else "send_private_msg"
        target_key = "group_id" if is_group else "user_id"
        result = await self._call_api(
            action,
            {
                target_key: int(chat_id),
                "message": segments,
            },
        )
        if result is None:
            logger.warning("NapCat media send failed to {}", chat_id)

    async def _build_media_segment(self, media_path: str) -> dict[str, Any] | None:
        """Build a OneBot media segment from a local path or remote URL."""
        if media_path.startswith(("http://", "https://")):
            file_param = media_path
        else:
            file_param = await self._encode_media_file(media_path)
            if file_param is None:
                return None

        suffix = Path(media_path).suffix.lower()
        segment_type = "record" if suffix in {".mp3", ".wav", ".ogg", ".amr", ".silk", ".m4a"} else "image"
        return {"type": segment_type, "data": {"file": file_param}}

    async def _encode_media_file(self, media_path: str) -> str | None:
        """Encode a local file for websocket transport so NapCat does not need host path access."""
        try:
            raw = await asyncio.to_thread(Path(media_path).read_bytes)
        except OSError as exc:
            logger.warning("NapCat failed to read local media {}: {}", media_path, exc)
            return None
        return f"base64://{base64.b64encode(raw).decode('ascii')}"

    async def _call_api(self, action: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Call OneBot API and wait for response."""
        if not self._ws:
            return None

        self._echo_counter += 1
        echo = f"nanobot:{self._echo_counter}"
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_responses[echo] = future

        try:
            await self._ws.send(json.dumps({"action": action, "params": params or {}, "echo": echo}, ensure_ascii=False))
            result = await asyncio.wait_for(future, timeout=10.0)
            return result
        except asyncio.TimeoutError:
            logger.warning("NapCat API call {} timed out", action)
            return None
        finally:
            self._pending_responses.pop(echo, None)

    async def _handle_ws_message(self, raw: str) -> None:
        """Handle a raw websocket frame from NapCat."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid NapCat JSON: {}", raw[:200])
            return

        if not isinstance(data, dict):
            return

        if data.get("self_id") is not None:
            self._self_id = str(data["self_id"])

        if "echo" in data:
            future = self._pending_responses.get(str(data["echo"]))
            if future and not future.done():
                if data.get("status") == "ok":
                    future.set_result(data.get("data", {}))
                else:
                    logger.warning(
                        "NapCat action {} failed: status={} retcode={} message={}",
                        data.get("echo"), data.get("status"), data.get("retcode"), data.get("message"),
                    )
                    future.set_result(None)
            return

        post_type = data.get("post_type")
        if post_type == "message":
            await self._handle_event(data)
        elif post_type == "notice" and self.config.handle_notice_events:
            await self._handle_notice_event(data)
        elif post_type == "request" and self.config.handle_request_events:
            await self._handle_request_event(data)

    async def _handle_event(self, event: dict[str, Any]) -> None:
        """Handle an inbound OneBot message event."""
        message_id = str(event.get("message_id") or "")
        if message_id:
            if message_id in self._processed_ids:
                return
            self._processed_ids[message_id] = None
            while len(self._processed_ids) > 1000:
                self._processed_ids.popitem(last=False)

        user_id = str(event.get("user_id") or "")
        if not user_id:
            return

        if self._self_id and user_id == self._self_id:
            return

        message_type = str(event.get("message_type") or "")
        if message_type == "group":
            chat_id = str(event.get("group_id") or "")
            self._chat_type_cache[chat_id] = "group"
        elif message_type == "private":
            chat_id = user_id
            self._chat_type_cache[chat_id] = "private"
        else:
            return

        segments = event.get("message")
        text, media = await self._parse_segments(segments, user_id)

        if message_type == "group" and self.config.group_policy == "mention":
            if not self._contains_self_mention(segments):
                return

        if message_type == "group":
            text = self._prefix_group_text(event, text, bool(media))

        if not text and not media:
            return

        metadata = {
            "message_id": message_id,
            "is_group": message_type == "group",
            "sender_name": self._sender_name(event),
        }

        if self.config.message_debounce_enabled:
            await self._debounce_message(
                buffer_key=f"{message_type}:{chat_id}:{user_id}",
                sender_id=user_id,
                chat_id=chat_id,
                content=text,
                media=media,
                metadata=metadata,
            )
            return

        await self._handle_message(
            sender_id=user_id,
            chat_id=chat_id,
            content=text,
            media=media,
            metadata=metadata,
        )

    def _sender_name(self, event: dict[str, Any]) -> str:
        """Resolve the best-effort sender display name."""
        sender = event.get("sender")
        if isinstance(sender, dict):
            for key in ("card", "nickname", "nick", "user_name"):
                value = sender.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return str(event.get("user_id") or "unknown")

    def _prefix_group_text(self, event: dict[str, Any], text: str, has_media: bool) -> str:
        """Prefix group messages with the sender username."""
        sender_name = self._sender_name(event)
        if text:
            return f"{sender_name}: {text}"
        if has_media:
            return f"{sender_name}: [media]"
        return ""

    def _contains_self_mention(self, segments: Any) -> bool:
        """Check whether the message explicitly @mentions this bot."""
        if not isinstance(segments, list) or not self._self_id:
            return False
        for segment in segments:
            if not isinstance(segment, dict) or segment.get("type") != "at":
                continue
            qq = str((segment.get("data") or {}).get("qq") or "")
            if qq == self._self_id:
                return True
        return False

    async def _parse_segments(self, segments: Any, user_id: str) -> tuple[str, list[str]]:
        """Extract visible text, download images, and transcribe audio."""
        if isinstance(segments, str):
            return segments.strip(), []
        if not isinstance(segments, list):
            return "", []

        parts: list[str] = []
        media: list[str] = []

        for segment in segments:
            if not isinstance(segment, dict):
                continue
            data = segment.get("data") or {}
            seg_type = segment.get("type")

            if seg_type == "text":
                text = str(data.get("text") or "")
                if text:
                    parts.append(text)
                continue

            if seg_type == "image":
                url = str(data.get("url") or data.get("file") or "").strip()
                if not url:
                    continue
                path = await self._download_media(url, user_id, "image")
                if path:
                    media.append(path)
                    parts.append("[image]")
                continue

            if seg_type == "record":
                url = str(data.get("url") or data.get("file") or "").strip()
                if not url:
                    continue
                path = await self._download_media(url, user_id, "audio")
                if not path:
                    continue
                transcript = await self.transcribe_audio(path)
                parts.append(f"[voice] {transcript}".strip() if transcript else "[voice]")
                continue

        return "".join(parts).strip(), media

    async def _download_media(self, url: str, user_id: str, kind: Literal["image", "audio"]) -> str | None:
        """Download inbound media to the NapCat media directory."""
        if not self._http:
            return None

        try:
            response = await self._http.get(url)
            response.raise_for_status()
        except Exception as e:
            logger.warning("NapCat failed to download {} for {}: {}", kind, user_id, e)
            return None

        media_dir = get_media_dir("napcat")
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix
        if not suffix:
            if kind == "image":
                suffix = mimetypes.guess_extension("image/jpeg") or ".jpg"
            else:
                suffix = ".mp3"
        file_path = media_dir / f"{user_id}_{kind}_{asyncio.get_running_loop().time():.6f}".replace(".", "_")
        file_path = file_path.with_suffix(suffix)
        file_path.write_bytes(response.content)
        return str(file_path)

    async def _handle_notice_event(self, event: dict[str, Any]) -> None:
        """Handle notice events via logs only."""
        logger.info(
            "NapCat notice: type={} group_id={} user_id={}",
            event.get("notice_type"),
            event.get("group_id"),
            event.get("user_id"),
        )

    async def _handle_request_event(self, event: dict[str, Any]) -> None:
        """Handle request events via logs only."""
        logger.info(
            "NapCat request: type={} sub_type={} user_id={} group_id={} comment={}",
            event.get("request_type"),
            event.get("sub_type"),
            event.get("user_id"),
            event.get("group_id"),
            event.get("comment"),
        )

    async def _debounce_message(
        self,
        buffer_key: str,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str],
        metadata: dict[str, Any],
    ) -> None:
        """Buffer bursts of messages from the same sender/chat and flush them together."""
        bucket = self._message_buffer.setdefault(buffer_key, [])

        if len(bucket) >= self.config.message_debounce_max_messages:
            await self._flush_buffered_messages(buffer_key, sender_id, chat_id, metadata)
            bucket = self._message_buffer.setdefault(buffer_key, [])

        bucket.append({"content": content, "media": media, "metadata": metadata})

        old_task = self._debounce_timers.get(buffer_key)
        if old_task and not old_task.done():
            old_task.cancel()

        async def timer_callback() -> None:
            try:
                await asyncio.sleep(self.config.message_debounce_seconds)
                await self._flush_buffered_messages(buffer_key, sender_id, chat_id, metadata)
            except asyncio.CancelledError:
                pass

        self._debounce_timers[buffer_key] = asyncio.create_task(timer_callback())

    async def _flush_buffered_messages(
        self,
        buffer_key: str,
        sender_id: str,
        chat_id: str,
        metadata: dict[str, Any],
    ) -> None:
        """Flush buffered messages as one inbound turn."""
        messages = self._message_buffer.pop(buffer_key, [])
        self._debounce_timers.pop(buffer_key, None)
        if not messages:
            return

        content = "\n".join(m["content"] for m in messages if m["content"]).strip()
        media: list[str] = []
        final_metadata = dict(metadata)
        for item in messages:
            media.extend(item["media"])
            final_metadata.update(item["metadata"])

        if not content and not media:
            return

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media,
            metadata=final_metadata,
        )
