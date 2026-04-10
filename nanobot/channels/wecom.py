"""WeCom (Enterprise WeChat) channel implementation using wecom_aibot_sdk."""

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from pydantic import Field

WECOM_AVAILABLE = importlib.util.find_spec("wecom_aibot_sdk") is not None

# Upload safety limits (matching QQ channel defaults)
WECOM_UPLOAD_MAX_BYTES = 1024 * 1024 * 200  # 200MB

# Replace unsafe characters with "_", keep Chinese and common safe punctuation.
_SAFE_NAME_RE = re.compile(r"[^\w.\-()\[\]（）【】\u4e00-\u9fff]+", re.UNICODE)


def _sanitize_filename(name: str) -> str:
    """Sanitize filename to avoid traversal and problematic chars."""
    name = (name or "").strip()
    name = Path(name).name
    name = _SAFE_NAME_RE.sub("_", name).strip("._ ")
    return name


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_VIDEO_EXTS = {".mp4", ".avi", ".mov"}
_AUDIO_EXTS = {".amr", ".mp3", ".wav", ".ogg"}


def _guess_wecom_media_type(filename: str) -> str:
    """Classify file extension as WeCom media_type string."""
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "voice"
    return "file"

# ═══════════════════════════════════════════════════════════════════════════
# Multi-level Memory Manager for WeCom
# ═══════════════════════════════════════════════════════════════════════════
# Directory layout under workspace:
#   memory/MEMORY.md              ← shared public memory (skills, methods, knowledge)
#   wecom_users/
#     _config.json                ← admin binding, user registry
#     <userid>/
#       MEMORY.md                 ← private memory (preferences, habits, personal)
#       HISTORY.md                ← private history summary
#
# Design goal: prevent cross-user information leakage in group chats.
# Each user's private memory is isolated by userid directory; the context
# patch only injects the *current sender's* private memory into the prompt,
# never another user's data.
# ═══════════════════════════════════════════════════════════════════════════


def _now_str() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class WecomMemoryManager:
    """Manages per-user private memory + shared public memory for WeCom users.

    In group chats multiple users share the same chat_id session, so it is
    critical that each user's private MEMORY.md is stored under their own
    userid directory and only injected for the user who sent the current
    message — never leaked to other participants.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.users_dir = workspace / "wecom_users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self.users_dir / "_config.json"
        self._config = self._load_config()

    # ── Config persistence ──────────────────────────────────────────────

    def _load_config(self) -> dict:
        if self._config_path.exists():
            try:
                return json.loads(self._config_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"admin_ids": [], "users": {}}

    def _save_config(self) -> None:
        self._config_path.write_text(
            json.dumps(self._config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Admin management ────────────────────────────────────────────────

    def is_admin(self, userid: str) -> bool:
        return userid in self._config.get("admin_ids", [])

    def add_admin(self, userid: str) -> None:
        admins = self._config.setdefault("admin_ids", [])
        if userid not in admins:
            admins.append(userid)
            self._save_config()

    # ── User directory ──────────────────────────────────────────────────

    def _user_dir(self, userid: str) -> Path:
        d = self.users_dir / userid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ensure_user_registered(self, userid: str, name: str = "") -> None:
        users = self._config.setdefault("users", {})
        if userid not in users:
            users[userid] = {"name": name, "first_seen": _now_str()}
            self._save_config()
        elif name and not users[userid].get("name"):
            users[userid]["name"] = name
            self._save_config()

    def get_user_display(self, userid: str) -> str:
        info = self._config.get("users", {}).get(userid, {})
        name = info.get("name", "")
        return f"{name} ({userid})" if name else userid

    # ── Per-user private memory ─────────────────────────────────────────

    def read_user_memory(self, userid: str) -> str:
        p = self._user_dir(userid) / "MEMORY.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write_user_memory(self, userid: str, content: str) -> None:
        p = self._user_dir(userid) / "MEMORY.md"
        p.write_text(content, encoding="utf-8")

    # ── Shared public memory ────────────────────────────────────────────

    def read_public_memory(self) -> str:
        p = self.workspace / "memory" / "MEMORY.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""


# Global instance — initialized lazily by WecomChannel
_memory_mgr: WecomMemoryManager | None = None


def get_memory_manager(workspace: Path) -> WecomMemoryManager:
    global _memory_mgr
    if _memory_mgr is None or _memory_mgr.workspace != workspace:
        _memory_mgr = WecomMemoryManager(workspace)
    return _memory_mgr


# ═══════════════════════════════════════════════════════════════════════════
# Monkey-patch: inject per-user memory into system prompt
# ═══════════════════════════════════════════════════════════════════════════
# Only the *current sender's* private memory is injected, preventing any
# cross-user data leakage in group chats where multiple users share a session.

_context_patch_applied = False
# Maps "wecom:<chat_id>" → sender_id of the most recent message in that chat
_latest_sender: dict[str, str] = {}


def _apply_context_patch() -> None:
    """Patch ContextBuilder.build_system_prompt to append per-user WeCom memory."""
    global _context_patch_applied
    if _context_patch_applied:
        return
    _context_patch_applied = True

    from nanobot.agent.context import ContextBuilder
    _orig_build = ContextBuilder.build_system_prompt

    def _patched_build_system_prompt(self, skill_names=None):
        base = _orig_build(self, skill_names)

        active_senders = set(_latest_sender.values())
        if not active_senders:
            return base

        mgr = get_memory_manager(self.workspace)

        # Build per-user memory sections — only inject memory for users who
        # have private MEMORY.md; never mix memories between users.
        user_memory_parts = []
        for sid in active_senders:
            priv = mgr.read_user_memory(sid)
            if priv:
                display = mgr.get_user_display(sid)
                role = "管理员" if mgr.is_admin(sid) else "用户"
                user_memory_parts.append(
                    f"### {display} ({role}) 的私有记忆\n{priv}"
                )

        instruction = (
            "\n\n---\n\n"
            "# WeCom 多级记忆系统\n\n"
            "你有两层记忆可用：\n"
            "1. **公共记忆** (`memory/MEMORY.md`): 存放技能、方法、知识等所有人可见的信息\n"
            "2. **私有记忆** (`wecom_users/<userid>/MEMORY.md`): 存放个人偏好、习惯、隐私信息\n\n"
            "当用户要求记住某些内容时，请判断分类：\n"
            "- 个人偏好/习惯/隐私 → 用 write_file 写入 `wecom_users/<userid>/MEMORY.md`\n"
            "- 技能/方法/通用知识 → 用 edit_file 编辑 `memory/MEMORY.md`\n"
            "- **严禁**将某用户的私有记忆泄露给其他用户（群聊中尤其注意）\n"
            "- 查看某人私有记忆需要管理员权限或本人请求\n"
        )
        if user_memory_parts:
            instruction += "\n" + "\n\n".join(user_memory_parts)

        return base + instruction

    ContextBuilder.build_system_prompt = _patched_build_system_prompt
    logger.info("ContextBuilder patched: per-user WeCom memory enabled")


class WecomConfig(Base):
    """WeCom (Enterprise WeChat) AI Bot channel configuration."""

    enabled: bool = False
    bot_id: str = ""
    secret: str = ""
    allow_from: list[str] = Field(default_factory=list)
    welcome_message: str = ""


# Message type display mapping
MSG_TYPE_MAP = {
    "image": "[image]",
    "voice": "[voice]",
    "file": "[file]",
    "mixed": "[mixed content]",
}


class WecomChannel(BaseChannel):
    """
    WeCom (Enterprise WeChat) channel using WebSocket long connection.

    Uses WebSocket to receive events - no public IP or webhook required.

    Requires:
    - Bot ID and Secret from WeCom AI Bot platform
    """

    name = "wecom"
    display_name = "WeCom"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WecomConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WecomConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WecomConfig = config
        self._client: Any = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generate_req_id = None
        # Store frame headers for each chat to enable replies
        self._chat_frames: dict[str, Any] = {}

    async def start(self) -> None:
        """Start the WeCom bot with WebSocket long connection."""
        if not WECOM_AVAILABLE:
            logger.error("WeCom SDK not installed. Run: pip install nanobot-ai[wecom]")
            return

        if not self.config.bot_id or not self.config.secret:
            logger.error("WeCom bot_id and secret not configured")
            return

        from wecom_aibot_sdk import WSClient, generate_req_id

        # Apply context patch for per-user memory isolation
        _apply_context_patch()

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._generate_req_id = generate_req_id

        # Create WebSocket client
        self._client = WSClient({
            "bot_id": self.config.bot_id,
            "secret": self.config.secret,
            "reconnect_interval": 1000,
            "max_reconnect_attempts": -1,  # Infinite reconnect
            "heartbeat_interval": 30000,
        })

        # Register event handlers
        self._client.on("connected", self._on_connected)
        self._client.on("authenticated", self._on_authenticated)
        self._client.on("disconnected", self._on_disconnected)
        self._client.on("error", self._on_error)
        self._client.on("message.text", self._on_text_message)
        self._client.on("message.image", self._on_image_message)
        self._client.on("message.voice", self._on_voice_message)
        self._client.on("message.file", self._on_file_message)
        self._client.on("message.mixed", self._on_mixed_message)
        self._client.on("event.enter_chat", self._on_enter_chat)

        logger.info("WeCom bot starting with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")

        # Connect
        await self._client.connect_async()

        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the WeCom bot."""
        self._running = False
        if self._client:
            await self._client.disconnect()
        logger.info("WeCom bot stopped")

    async def _on_connected(self, frame: Any) -> None:
        """Handle WebSocket connected event."""
        logger.info("WeCom WebSocket connected")

    async def _on_authenticated(self, frame: Any) -> None:
        """Handle authentication success event."""
        logger.info("WeCom authenticated successfully")

    async def _on_disconnected(self, frame: Any) -> None:
        """Handle WebSocket disconnected event."""
        reason = frame.body if hasattr(frame, 'body') else str(frame)
        logger.warning("WeCom WebSocket disconnected: {}", reason)

    async def _on_error(self, frame: Any) -> None:
        """Handle error event."""
        logger.error("WeCom error: {}", frame)

    async def _on_text_message(self, frame: Any) -> None:
        """Handle text message."""
        await self._process_message(frame, "text")

    async def _on_image_message(self, frame: Any) -> None:
        """Handle image message."""
        await self._process_message(frame, "image")

    async def _on_voice_message(self, frame: Any) -> None:
        """Handle voice message."""
        await self._process_message(frame, "voice")

    async def _on_file_message(self, frame: Any) -> None:
        """Handle file message."""
        await self._process_message(frame, "file")

    async def _on_mixed_message(self, frame: Any) -> None:
        """Handle mixed content message."""
        await self._process_message(frame, "mixed")

    async def _on_enter_chat(self, frame: Any) -> None:
        """Handle enter_chat event (user opens chat with bot)."""
        try:
            # Extract body from WsFrame dataclass or dict
            if hasattr(frame, 'body'):
                body = frame.body or {}
            elif isinstance(frame, dict):
                body = frame.get("body", frame)
            else:
                body = {}

            chat_id = body.get("chatid", "") if isinstance(body, dict) else ""

            if chat_id and self.config.welcome_message:
                await self._client.reply_welcome(frame, {
                    "msgtype": "text",
                    "text": {"content": self.config.welcome_message},
                })
        except Exception as e:
            logger.error("Error handling enter_chat: {}", e)

    async def _process_message(self, frame: Any, msg_type: str) -> None:
        """Process incoming message and forward to bus."""
        try:
            # Extract body from WsFrame dataclass or dict
            if hasattr(frame, 'body'):
                body = frame.body or {}
            elif isinstance(frame, dict):
                body = frame.get("body", frame)
            else:
                body = {}

            # Ensure body is a dict
            if not isinstance(body, dict):
                logger.warning("Invalid body type: {}", type(body))
                return

            # Extract message info
            msg_id = body.get("msgid", "")
            if not msg_id:
                msg_id = f"{body.get('chatid', '')}_{body.get('sendertime', '')}"

            # Deduplication check
            if msg_id in self._processed_message_ids:
                return
            self._processed_message_ids[msg_id] = None

            # Trim cache
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # Extract sender info from "from" field (SDK format)
            from_info = body.get("from", {})
            sender_id = from_info.get("userid", "unknown") if isinstance(from_info, dict) else "unknown"
            sender_name = from_info.get("name", "") if isinstance(from_info, dict) else ""

            # For single chat, chatid is the sender's userid
            # For group chat, chatid is provided in body
            chat_type = body.get("chattype", "single")
            chat_id = body.get("chatid", sender_id)

            # Register user in memory manager and track latest sender per chat.
            # This enables the context patch to inject only the current sender's
            # private memory — preventing cross-user leakage in group chats.
            try:
                from nanobot.config.loader import load_config
                workspace = load_config().workspace_path
                mgr = get_memory_manager(workspace)
                mgr.ensure_user_registered(sender_id, sender_name)
                _latest_sender[f"wecom:{chat_id}"] = sender_id
            except Exception as exc:
                logger.warning("Failed to register user in memory manager: {}", exc)

            content_parts = []
            media_paths: list[str] = []

            if msg_type == "text":
                text = body.get("text", {}).get("content", "")
                if text:
                    content_parts.append(text)

            elif msg_type == "image":
                image_info = body.get("image", {})
                file_url = image_info.get("url", "")
                aes_key = image_info.get("aeskey", "")

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "image")
                    if file_path:
                        filename = os.path.basename(file_path)
                        content_parts.append(f"[image: {filename}]")
                        media_paths.append(file_path)
                    else:
                        content_parts.append("[image: download failed]")
                else:
                    content_parts.append("[image: download failed]")

            elif msg_type == "voice":
                voice_info = body.get("voice", {})
                # Voice message already contains transcribed content from WeCom
                voice_content = voice_info.get("content", "")
                if voice_content:
                    content_parts.append(f"[voice] {voice_content}")
                else:
                    content_parts.append("[voice]")

            elif msg_type == "file":
                file_info = body.get("file", {})
                file_url = file_info.get("url", "")
                aes_key = file_info.get("aeskey", "")
                file_name = file_info.get("name", "unknown")

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "file", file_name)
                    if file_path:
                        content_parts.append(f"[file: {file_name}]")
                        media_paths.append(file_path)
                    else:
                        content_parts.append(f"[file: {file_name}: download failed]")
                else:
                    content_parts.append(f"[file: {file_name}: download failed]")

            elif msg_type == "mixed":
                # Mixed content contains multiple message items
                msg_items = body.get("mixed", {}).get("item", [])
                for item in msg_items:
                    item_type = item.get("type", "")
                    if item_type == "text":
                        text = item.get("text", {}).get("content", "")
                        if text:
                            content_parts.append(text)
                    else:
                        content_parts.append(MSG_TYPE_MAP.get(item_type, f"[{item_type}]"))

            else:
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            content = "\n".join(content_parts) if content_parts else ""

            if not content:
                return

            # Store frame for this chat to enable replies
            self._chat_frames[chat_id] = frame

            # Forward to message bus
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media_paths or None,
                metadata={
                    "message_id": msg_id,
                    "msg_type": msg_type,
                    "chat_type": chat_type,
                }
            )

        except Exception as e:
            logger.error("Error processing WeCom message: {}", e)

    async def _download_and_save_media(
        self,
        file_url: str,
        aes_key: str,
        media_type: str,
        filename: str | None = None,
    ) -> str | None:
        """
        Download and decrypt media from WeCom.

        Returns:
            file_path or None if download failed
        """
        try:
            data, fname = await self._client.download_file(file_url, aes_key)

            if not data:
                logger.warning("Failed to download media from WeCom")
                return None

            if len(data) > WECOM_UPLOAD_MAX_BYTES:
                logger.warning(
                    "WeCom inbound media too large: {} bytes (max {})",
                    len(data),
                    WECOM_UPLOAD_MAX_BYTES,
                )
                return None

            media_dir = get_media_dir("wecom")
            if not filename:
                filename = fname or f"{media_type}_{hash(file_url) % 100000}"
            filename = _sanitize_filename(filename)

            file_path = media_dir / filename
            await asyncio.to_thread(file_path.write_bytes, data)
            logger.debug("Downloaded {} to {}", media_type, file_path)
            return str(file_path)

        except Exception as e:
            logger.error("Error downloading media: {}", e)
            return None

    async def _upload_media_ws(
        self, client: Any, file_path: str,
    ) -> "tuple[str, str] | tuple[None, None]":
        """Upload a local file to WeCom via WebSocket 3-step protocol (base64).

        Uses the WeCom WebSocket upload commands directly via
        ``client._ws_manager.send_reply()``:

          ``aibot_upload_media_init``   → upload_id
          ``aibot_upload_media_chunk`` × N  (≤512 KB raw per chunk, base64)
          ``aibot_upload_media_finish`` → media_id

        Returns (media_id, media_type) on success, (None, None) on failure.
        """
        from wecom_aibot_sdk.utils import generate_req_id as _gen_req_id

        try:
            fname = os.path.basename(file_path)
            media_type = _guess_wecom_media_type(fname)

            # Read file size and data in a thread to avoid blocking the event loop
            def _read_file():
                file_size = os.path.getsize(file_path)
                if file_size > WECOM_UPLOAD_MAX_BYTES:
                    raise ValueError(
                        f"File too large: {file_size} bytes (max {WECOM_UPLOAD_MAX_BYTES})"
                    )
                with open(file_path, "rb") as f:
                    return file_size, f.read()

            file_size, data = await asyncio.to_thread(_read_file)
            # MD5 is used for file integrity only, not cryptographic security
            md5_hash = hashlib.md5(data).hexdigest()

            CHUNK_SIZE = 512 * 1024  # 512 KB raw (before base64)
            mv = memoryview(data)
            chunk_list = [bytes(mv[i : i + CHUNK_SIZE]) for i in range(0, file_size, CHUNK_SIZE)]
            n_chunks = len(chunk_list)
            del mv, data

            # Step 1: init
            req_id = _gen_req_id("upload_init")
            resp = await client._ws_manager.send_reply(req_id, {
                "type": media_type,
                "filename": fname,
                "total_size": file_size,
                "total_chunks": n_chunks,
                "md5": md5_hash,
            }, "aibot_upload_media_init")
            if resp.errcode != 0:
                logger.warning("WeCom upload init failed ({}): {}", resp.errcode, resp.errmsg)
                return None, None
            upload_id = resp.body.get("upload_id") if resp.body else None
            if not upload_id:
                logger.warning("WeCom upload init: no upload_id in response")
                return None, None

            # Step 2: send chunks
            for i, chunk in enumerate(chunk_list):
                req_id = _gen_req_id("upload_chunk")
                resp = await client._ws_manager.send_reply(req_id, {
                    "upload_id": upload_id,
                    "chunk_index": i,
                    "base64_data": base64.b64encode(chunk).decode(),
                }, "aibot_upload_media_chunk")
                if resp.errcode != 0:
                    logger.warning("WeCom upload chunk {} failed ({}): {}", i, resp.errcode, resp.errmsg)
                    return None, None

            # Step 3: finish
            req_id = _gen_req_id("upload_finish")
            resp = await client._ws_manager.send_reply(req_id, {
                "upload_id": upload_id,
            }, "aibot_upload_media_finish")
            if resp.errcode != 0:
                logger.warning("WeCom upload finish failed ({}): {}", resp.errcode, resp.errmsg)
                return None, None

            media_id = resp.body.get("media_id") if resp.body else None
            if not media_id:
                logger.warning("WeCom upload finish: no media_id in response body={}", resp.body)
                return None, None

            suffix = "..." if len(media_id) > 16 else ""
            logger.debug("WeCom uploaded {} ({}) → media_id={}", fname, media_type, media_id[:16] + suffix)
            return media_id, media_type

        except ValueError as e:
            logger.warning("WeCom upload skipped for {}: {}", file_path, e)
            return None, None
        except Exception as e:
            logger.error("WeCom _upload_media_ws error for {}: {}", file_path, e)
            return None, None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WeCom."""
        if not self._client:
            logger.warning("WeCom client not initialized")
            return

        try:
            content = (msg.content or "").strip()
            is_progress = bool(msg.metadata.get("_progress"))

            # Get the stored frame for this chat
            frame = self._chat_frames.get(msg.chat_id)

            # Send media files via WebSocket upload
            for file_path in msg.media or []:
                if not os.path.isfile(file_path):
                    logger.warning("WeCom media file not found: {}", file_path)
                    continue
                media_id, media_type = await self._upload_media_ws(self._client, file_path)
                if media_id:
                    if frame:
                        await self._client.reply(frame, {
                            "msgtype": media_type,
                            media_type: {"media_id": media_id},
                        })
                    else:
                        await self._client.send_message(msg.chat_id, {
                            "msgtype": media_type,
                            media_type: {"media_id": media_id},
                        })
                    logger.debug("WeCom sent {} → {}", media_type, msg.chat_id)
                else:
                    content += f"\n[file upload failed: {os.path.basename(file_path)}]"

            if not content:
                return

            if frame:
                if is_progress:
                    # Progress messages (thinking text): send as plain reply, no streaming
                    await self._client.reply(frame, {
                        "msgtype": "text",
                        "text": {"content": content},
                    })
                    logger.debug("WeCom progress sent to {}", msg.chat_id)
                else:
                    # Final response: use streaming reply for better UX
                    stream_id = self._generate_req_id("stream")
                    await self._client.reply_stream(
                        frame,
                        stream_id,
                        content,
                        finish=True,
                    )
                    logger.debug("WeCom message sent to {}", msg.chat_id)
            else:
                # No frame (e.g. cron push): proactive send only supports markdown
                await self._client.send_message(msg.chat_id, {
                    "msgtype": "markdown",
                    "markdown": {"content": content},
                })
                logger.info("WeCom proactive send to {}", msg.chat_id)

        except Exception:
            logger.exception("Error sending WeCom message to chat_id={}", msg.chat_id)
