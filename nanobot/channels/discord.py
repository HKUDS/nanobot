"""Discord channel implementation using Discord Gateway websocket."""

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import Field
import websockets
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.tts.service import TTSService
from nanobot.utils.helpers import split_message

DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000  # Discord message character limit


class DiscordConfig(Base):
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"
    slash_commands: bool = True  # 注册 Discord slash commands


class DiscordChannel(BaseChannel):
    """Discord channel using Gateway websocket."""

    name = "discord"
    display_name = "Discord"
    supports_tts = True

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return DiscordConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus, tts_service: TTSService | None = None):
        if isinstance(config, dict):
            config = DiscordConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: DiscordConfig = config
        self._tts_service = tts_service
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._seq: int | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._http: httpx.AsyncClient | None = None
        self._bot_user_id: str | None = None
        self._app_id: str | None = None
        self._channel_name_cache: dict[str, str] = {}  # channel_id -> name
        self._channel_scope_cache: dict[str, str] = {}  # channel_id -> scope_id (parent for threads)

    async def start(self) -> None:
        """Start the Discord gateway connection."""
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)

        while self._running:
            try:
                logger.info("Connecting to Discord gateway...")
                async with websockets.connect(self.config.gateway_url) as ws:
                    self._ws = ws
                    await self._gateway_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Discord gateway error: {}", e)
                if self._running:
                    logger.info("Reconnecting to Discord gateway in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Discord REST API, including file attachments."""
        if not self._http:
            logger.warning("Discord HTTP client not initialized")
            return

        # Slash command 响应：走 interaction followup 路径
        interaction_token = (msg.metadata or {}).get("interaction_token")
        if interaction_token:
            await self._send_interaction_followup(msg, interaction_token)
            return

        # TTS: generate audio attachment (text is preserved)
        if self._tts_service and msg.content and not msg.metadata.get("_progress"):
            session_tts = msg.metadata.get("_session_tts", False)
            sender_name = msg.metadata.get("sender_name")
            logger.debug("TTS check: sender_name={}, session_tts={}, auto_senders={}",
                         sender_name, session_tts, self._tts_service.config.auto_tts_senders)
            if self._tts_service.should_trigger(session_tts=session_tts, sender_name=sender_name):
                audio_path = await self._tts_service.synthesize(msg.content)
                if audio_path:
                    if not msg.media:
                        msg.media = []
                    msg.media.insert(0, str(audio_path))

        url = f"{DISCORD_API_BASE}/channels/{msg.chat_id}/messages"
        headers = {"Authorization": f"Bot {self.config.token}"}

        try:
            sent_media = False
            failed_media: list[str] = []

            # Send file attachments first
            for media_path in msg.media or []:
                if await self._send_file(url, headers, media_path, reply_to=msg.reply_to):
                    sent_media = True
                else:
                    failed_media.append(Path(media_path).name)

            # Send text content
            chunks = split_message(msg.content or "", MAX_MESSAGE_LEN)
            if not chunks and failed_media and not sent_media:
                chunks = split_message(
                    "\n".join(f"[attachment: {name} - send failed]" for name in failed_media),
                    MAX_MESSAGE_LEN,
                )
            if not chunks:
                return

            for i, chunk in enumerate(chunks):
                payload: dict[str, Any] = {"content": chunk}

                # Let the first successful attachment carry the reply if present.
                if i == 0 and msg.reply_to and not sent_media:
                    payload["message_reference"] = {"message_id": msg.reply_to}
                    payload["allowed_mentions"] = {"replied_user": False}

                if not await self._send_payload(url, headers, payload):
                    break  # Abort remaining chunks on failure
        finally:
            await self._stop_typing(msg.chat_id)

    async def _send_payload(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> bool:
        """Send a single Discord API payload with retry on rate-limit. Returns True on success."""
        for attempt in range(3):
            try:
                response = await self._http.post(url, headers=headers, json=payload)
                if response.status_code == 429:
                    data = response.json()
                    retry_after = float(data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord message: {}", e)
                else:
                    await asyncio.sleep(1)
        return False

    async def _send_file(
        self,
        url: str,
        headers: dict[str, str],
        file_path: str,
        reply_to: str | None = None,
    ) -> bool:
        """Send a file attachment via Discord REST API using multipart/form-data."""
        path = Path(file_path)
        if not path.is_file():
            logger.warning("Discord file not found, skipping: {}", file_path)
            return False

        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            logger.warning("Discord file too large (>20MB), skipping: {}", path.name)
            return False

        payload_json: dict[str, Any] = {}
        if reply_to:
            payload_json["message_reference"] = {"message_id": reply_to}
            payload_json["allowed_mentions"] = {"replied_user": False}

        for attempt in range(3):
            try:
                with open(path, "rb") as f:
                    files = {"files[0]": (path.name, f, "application/octet-stream")}
                    data: dict[str, Any] = {}
                    if payload_json:
                        data["payload_json"] = json.dumps(payload_json)
                    response = await self._http.post(
                        url, headers=headers, files=files, data=data
                    )
                if response.status_code == 429:
                    resp_data = response.json()
                    retry_after = float(resp_data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                logger.info("Discord file sent: {}", path.name)
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord file {}: {}", path.name, e)
                else:
                    await asyncio.sleep(1)
        return False

    async def _gateway_loop(self) -> None:
        """Main gateway loop: identify, heartbeat, dispatch events."""
        if not self._ws:
            return

        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from Discord gateway: {}", raw[:100])
                continue

            op = data.get("op")
            event_type = data.get("t")
            seq = data.get("s")
            payload = data.get("d")

            if seq is not None:
                self._seq = seq

            if op == 10:
                # HELLO: start heartbeat and identify
                interval_ms = payload.get("heartbeat_interval", 45000)
                await self._start_heartbeat(interval_ms / 1000)
                await self._identify()
            elif op == 0 and event_type == "READY":
                logger.info("Discord gateway READY")
                # Capture bot user ID for mention detection
                user_data = payload.get("user") or {}
                self._bot_user_id = user_data.get("id")
                logger.info("Discord bot connected as user {}", self._bot_user_id)
                # 注册 slash commands
                from nanobot.command.discord_slash import (
                    extract_app_id,
                    register_all_commands,
                    register_guild_commands,
                )
                try:
                    self._app_id = extract_app_id(self.config.token)
                except Exception as e:
                    logger.warning("Failed to extract app_id: {}", e)
                guild_ids = [str(g["id"]) for g in payload.get("guilds", [])]
                if guild_ids and self._app_id:
                    if self.config.slash_commands:
                        # 尝试构造 SkillsLoader 以注册 skill commands
                        skills_loader = self._make_skills_loader()
                        # 从 config 读取模型列表供 /model 下拉框使用
                        model_choices = self._load_model_choices()
                        asyncio.create_task(register_all_commands(
                            self._http, self.config.token, guild_ids,
                            skills_loader=skills_loader,
                            model_choices=model_choices,
                        ))
                    else:
                        # slash_commands 关闭时，PUT 空列表清除已注册的命令
                        for gid in guild_ids:
                            asyncio.create_task(register_guild_commands(
                                self._http, self._app_id, gid,
                                self.config.token, [],
                            ))
            elif op == 0 and event_type == "INTERACTION_CREATE":
                await self._handle_interaction(payload)
            elif op == 0 and event_type == "MESSAGE_CREATE":
                await self._handle_message_create(payload)
            elif op == 7:
                # RECONNECT: exit loop to reconnect
                logger.info("Discord gateway requested reconnect")
                break
            elif op == 9:
                # INVALID_SESSION: reconnect
                logger.warning("Discord gateway invalid session")
                break

    async def _identify(self) -> None:
        """Send IDENTIFY payload."""
        if not self._ws:
            return

        identify = {
            "op": 2,
            "d": {
                "token": self.config.token,
                "intents": self.config.intents,
                "properties": {
                    "os": "nanobot",
                    "browser": "nanobot",
                    "device": "nanobot",
                },
            },
        }
        await self._ws.send(json.dumps(identify))

    async def _start_heartbeat(self, interval_s: float) -> None:
        """Start or restart the heartbeat loop."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        async def heartbeat_loop() -> None:
            while self._running and self._ws:
                payload = {"op": 1, "d": self._seq}
                try:
                    await self._ws.send(json.dumps(payload))
                except Exception as e:
                    logger.warning("Discord heartbeat failed: {}", e)
                    break
                await asyncio.sleep(interval_s)

        self._heartbeat_task = asyncio.create_task(heartbeat_loop())

    async def _handle_message_create(self, payload: dict[str, Any]) -> None:
        """Handle incoming Discord messages."""
        author = payload.get("author") or {}
        webhook_id = payload.get("webhook_id")
        # 普通 bot 消息忽略，但 webhook 消息允许通过（author.id === webhook_id）
        if author.get("bot") and not webhook_id:
            return
        # 过滤自己的 interaction followup webhook 消息（app_id 即 webhook_id）
        if webhook_id and self._app_id and str(webhook_id) == str(self._app_id):
            return

        sender_id = str(author.get("id", ""))
        channel_id = str(payload.get("channel_id", ""))
        content = payload.get("content") or ""
        guild_id = payload.get("guild_id")

        # Resolve sender display name: guild nick > global_name > username
        member = payload.get("member") or {}
        sender_name = (
            member.get("nick")
            or author.get("global_name")
            or author.get("username")
        )

        if not sender_id or not channel_id:
            return

        if not self.is_allowed(sender_id):
            return

        # Check group channel policy (DMs always respond if is_allowed passes)
        if guild_id is not None:
            if not self._should_respond_in_group(payload, content):
                return

        content_parts = [content] if content else []
        media_paths: list[str] = []
        media_dir = get_media_dir("discord")

        for attachment in payload.get("attachments") or []:
            url = attachment.get("url")
            filename = attachment.get("filename") or "attachment"
            size = attachment.get("size") or 0
            if not url or not self._http:
                continue
            if size and size > MAX_ATTACHMENT_BYTES:
                content_parts.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                file_path = media_dir / f"{attachment.get('id', 'file')}_{filename.replace('/', '_')}"
                resp = await self._http.get(url)
                resp.raise_for_status()
                file_path.write_bytes(resp.content)
                media_paths.append(str(file_path))

                # Transcribe audio attachments (voice messages, audio files)
                content_type = attachment.get("content_type") or ""
                if content_type.startswith("audio/") or filename.endswith(
                    (".ogg", ".mp3", ".wav", ".m4a", ".flac", ".webm")
                ):
                    transcription = await self.transcribe_audio(file_path)
                    if transcription:
                        logger.info("Transcribed audio: {}...", transcription[:50])
                        content_parts.append(f"[transcription: {transcription}]")
                        continue

                content_parts.append(f"[attachment: {file_path}]")
            except Exception as e:
                logger.warning("Failed to download Discord attachment: {}", e)
                content_parts.append(f"[attachment: {filename} - download failed]")

        reply_to = (payload.get("referenced_message") or {}).get("id")

        # Resolve human-readable channel name (cached)
        channel_name = await self._resolve_channel_name(channel_id)

        await self._start_typing(channel_id)

        metadata: dict[str, Any] = {
            "message_id": str(payload.get("id", "")),
            "guild_id": guild_id,
            "reply_to": reply_to,
        }
        if channel_name:
            metadata["channel_name"] = channel_name
            metadata["channel_scope_id"] = self.get_channel_scope_id(channel_id)
        if sender_name:
            metadata["sender_name"] = sender_name

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content="\n".join(p for p in content_parts if p) or "[empty message]",
            media=media_paths,
            metadata=metadata,
        )

    def _should_respond_in_group(self, payload: dict[str, Any], content: str) -> bool:
        """Check if bot should respond in a group channel based on policy."""
        if self.config.group_policy == "open":
            return True

        if self.config.group_policy == "mention":
            # Check if bot was mentioned in the message
            if self._bot_user_id:
                # Check mentions array
                mentions = payload.get("mentions") or []
                for mention in mentions:
                    if str(mention.get("id")) == self._bot_user_id:
                        return True
                # Also check content for mention format <@USER_ID>
                if f"<@{self._bot_user_id}>" in content or f"<@!{self._bot_user_id}>" in content:
                    return True
            logger.debug("Discord message in {} ignored (bot not mentioned)", payload.get("channel_id"))
            return False

        return True

    async def _resolve_channel_name(self, channel_id: str) -> str | None:
        """Resolve channel_id to a human-readable name, with in-memory cache.

        For threads (type 10/11/12), resolves to the parent channel name so
        that skill filtering and other channel-name-based logic applies
        consistently across a channel and all its threads.
        """
        if channel_id in self._channel_name_cache:
            return self._channel_name_cache[channel_id]
        if not self._http:
            return None
        try:
            url = f"{DISCORD_API_BASE}/channels/{channel_id}"
            headers = {"Authorization": f"Bot {self.config.token}"}
            resp = await self._http.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            channel_type = data.get("type")

            # Thread → resolve parent channel name + cache scope_id
            if channel_type in (10, 11, 12) and data.get("parent_id"):
                parent_id = data["parent_id"]
                name = await self._resolve_channel_name(parent_id)
                # scope_id = parent channel ID (threads share parent's directory)
                self._channel_scope_cache[channel_id] = self._channel_scope_cache.get(parent_id, parent_id)
            # DM → dm-{username}
            elif channel_type == 1:
                recipients = data.get("recipients") or []
                if recipients:
                    name = f"dm-{recipients[0].get('username', channel_id)}"
                else:
                    name = f"dm-{channel_id}"
                self._channel_scope_cache[channel_id] = channel_id
            else:
                name = data.get("name")
                self._channel_scope_cache[channel_id] = channel_id

            if name:
                self._channel_name_cache[channel_id] = name
            return name
        except Exception as e:
            logger.debug("Failed to resolve Discord channel name for {}: {}", channel_id, e)
            return None

    def get_channel_scope_id(self, channel_id: str) -> str:
        """Return the scope ID for a channel (parent ID for threads, self for channels)."""
        return self._channel_scope_cache.get(channel_id, channel_id)

    async def _start_typing(self, channel_id: str) -> None:
        """Start periodic typing indicator for a channel."""
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            url = f"{DISCORD_API_BASE}/channels/{channel_id}/typing"
            headers = {"Authorization": f"Bot {self.config.token}"}
            while self._running:
                try:
                    await self._http.post(url, headers=headers)
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.debug("Discord typing indicator failed for {}: {}", channel_id, e)
                    return
                await asyncio.sleep(8)

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator for a channel."""
        task = self._typing_tasks.pop(channel_id, None)
        if task:
            task.cancel()

    def _make_skills_loader(self) -> "SkillsLoader | None":
        """尝试构造 SkillsLoader 供 slash command 注册使用。"""
        try:
            from nanobot.agent.skills import SkillsLoader
            from nanobot.config.loader import load_config
            config = load_config()
            return SkillsLoader(config.workspace_path)
        except Exception as e:
            logger.debug("Could not create SkillsLoader for slash commands: {}", e)
            return None

    def _load_model_choices(self) -> list[str] | None:
        """从 config 读取 model + fallbackModels 供 slash command choices 使用。"""
        try:
            from nanobot.config.loader import load_config
            config = load_config()
            defaults = config.agents.defaults
            return [defaults.model] + list(defaults.fallback_models or [])
        except Exception as e:
            logger.debug("Could not load model choices: {}", e)
            return None

    # ── Slash Command / Interaction 处理 ─────────────────────

    async def _interaction_respond(
        self, interaction_id: str, interaction_token: str,
        resp_type: int, content: str = "",
    ) -> bool:
        """发送 interaction callback。type=4 立即回复，type=5 deferred。

        Interaction callback 用 token URL 鉴权，不需要 Bot Authorization。
        """
        if not self._http:
            return False
        url = f"{DISCORD_API_BASE}/interactions/{interaction_id}/{interaction_token}/callback"
        payload: dict[str, Any] = {"type": resp_type}
        if content:
            payload["data"] = {"content": content}
        try:
            resp = await self._http.post(url, json=payload)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Interaction callback failed: {}", e)
            return False

    async def _handle_interaction(self, payload: dict[str, Any]) -> None:
        """处理 INTERACTION_CREATE：deferred ack → 还原为文本命令 → 入 bus。"""
        if payload.get("type") != 2:  # 只处理 APPLICATION_COMMAND
            return

        interaction_id = payload["id"]
        interaction_token = payload["token"]
        data = payload.get("data", {})
        command_name = data.get("name", "")

        # 提取调用者信息
        member = payload.get("member", {})
        user = member.get("user", {}) or payload.get("user", {})
        sender_id = str(user.get("id", ""))
        channel_id = str(payload.get("channel_id", ""))
        guild_id = payload.get("guild_id")

        if not sender_id or not channel_id:
            return

        # 权限检查
        if not self.is_allowed(sender_id):
            await self._interaction_respond(
                interaction_id, interaction_token,
                resp_type=4, content="⛔ Not authorized.",
            )
            return

        # 立刻 deferred ack（3秒限制）
        if not await self._interaction_respond(
            interaction_id, interaction_token, resp_type=5,
        ):
            logger.warning("Deferred ack failed for interaction {}, dropping", interaction_id)
            return

        # 从 options 提取参数，还原为文本命令
        options = data.get("options", [])
        args_parts = []
        for opt in options:
            args_parts.append(str(opt.get("value", "")))
        args = " ".join(args_parts).strip()

        content = f"/{command_name} {args}".strip() if args else f"/{command_name}"

        # sender display name
        sender_name = (
            member.get("nick")
            or user.get("global_name")
            or user.get("username")
        )

        channel_name = await self._resolve_channel_name(channel_id)
        metadata: dict[str, Any] = {
            "message_id": interaction_id,
            "guild_id": guild_id,
            "interaction_id": interaction_id,
            "interaction_token": interaction_token,
        }
        if channel_name:
            metadata["channel_name"] = channel_name
            metadata["channel_scope_id"] = self.get_channel_scope_id(channel_id)
        if sender_name:
            metadata["sender_name"] = sender_name

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content=content,
            media=[],
            metadata=metadata,
        )

    async def _send_interaction_followup(
        self, msg: OutboundMessage, interaction_token: str,
    ) -> None:
        """通过 interaction webhook followup 发送响应。

        Followup 有效期 15 分钟，无 3 秒限制。
        Token 过期时降级为 channel message。
        """
        if not self._http or not self._app_id:
            return

        url = f"{DISCORD_API_BASE}/webhooks/{self._app_id}/{interaction_token}"
        headers = {"Authorization": f"Bot {self.config.token}"}

        # TTS（复用现有逻辑）
        if self._tts_service and msg.content and not msg.metadata.get("_progress"):
            session_tts = msg.metadata.get("_session_tts", False)
            sender_name = msg.metadata.get("sender_name")
            if self._tts_service.should_trigger(session_tts=session_tts, sender_name=sender_name):
                audio_path = await self._tts_service.synthesize(msg.content)
                if audio_path:
                    if not msg.media:
                        msg.media = []
                    msg.media.insert(0, str(audio_path))

        # 文件附件
        sent_media: list[str] = []
        for media_path in msg.media or []:
            path = Path(media_path)
            if not path.is_file() or path.stat().st_size > MAX_ATTACHMENT_BYTES:
                continue
            try:
                with open(path, "rb") as f:
                    files = {"files[0]": (path.name, f, "application/octet-stream")}
                    resp = await self._http.post(url, headers=headers, files=files)
                    if resp.status_code == 404:
                        logger.warning("Interaction token expired, falling back to channel msg")
                        # fallback 时只发还没发过的 media
                        msg.media = [m for m in (msg.media or []) if m not in sent_media]
                        await self._send_channel_message_fallback(msg)
                        return
                    resp.raise_for_status()
                    sent_media.append(media_path)
            except Exception as e:
                logger.warning("Followup file send failed: {}", e)

        # 文本分片（复用 _send_payload 的 rate-limit 重试）
        chunks = split_message(msg.content or "", MAX_MESSAGE_LEN)
        for chunk in chunks:
            if not await self._send_payload(url, headers, {"content": chunk}):
                # 可能是 token 过期或其他错误，尝试 fallback
                msg.media = []
                await self._send_channel_message_fallback(msg)
                return

    async def _send_channel_message_fallback(self, msg: OutboundMessage) -> None:
        """Interaction token 过期时，降级为普通 channel message。"""
        # 清除 interaction metadata 防止递归
        clean_meta = dict(msg.metadata or {})
        clean_meta.pop("interaction_token", None)
        clean_meta.pop("interaction_id", None)
        msg.metadata = clean_meta
        await self.send(msg)
