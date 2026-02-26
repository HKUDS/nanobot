"""QQ channel implementation using botpy SDK."""

import asyncio
import os
import re
import subprocess
import urllib.request
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import QQConfig

try:
    import botpy
    from botpy.message import C2CMessage

    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False
    botpy = None
    C2CMessage = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage


def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """Create a botpy Client subclass bound to the given channel."""
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            super().__init__(intents=intents)

        async def on_ready(self):
            logger.info("QQ bot ready: {}", self.robot.name)

        async def on_c2c_message_create(self, message: "C2CMessage"):
            await channel._on_message(message)

        async def on_direct_message_create(self, message):
            await channel._on_message(message)

    return _Bot


class QQChannel(BaseChannel):
    """QQ channel using botpy SDK with WebSocket connection."""

    name = "qq"

    def __init__(self, config: QQConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._reply_seq: dict[str, int] = {}  # msg_id -> next msg_seq (must increment per msg_id)

    @staticmethod
    def _is_http_url(s: str) -> bool:
        return bool(re.match(r"^https?://", (s or "").strip(), flags=re.IGNORECASE))

    async def _download_to_media_dir(self, url: str, filename_hint: str = "") -> str | None:
        """Download a URL to ~/.nanobot/media and return local file path."""
        if not url:
            return None
        media_dir = Path.home() / ".nanobot" / "media"
        media_dir.mkdir(parents=True, exist_ok=True)

        def _safe_name(name: str) -> str:
            name = (name or "").strip() or "attachment"
            name = re.sub(r"[\\\\/:*?\"<>|]+", "_", name)
            if len(name) > 120:
                root, ext = os.path.splitext(name)
                name = root[:100] + ext
            return name

        fn = _safe_name(filename_hint or os.path.basename(url.split("?", 1)[0]) or "attachment")
        path = media_dir / fn

        try:
            await asyncio.to_thread(urllib.request.urlretrieve, url, str(path))
            return str(path)
        except Exception as e:
            logger.warning("Failed to download attachment: {} -> {} ({})", url, path, e)
            return None

    async def _upload_local_to_public_url(self, file_path: str) -> str | None:
        """
        QQ requires public URL for media sending (botpy).
        If media_upload_command is configured, run it to upload local file and capture URL from stdout.
        """
        cmd_tpl = (self.config.media_upload_command or "").strip()
        if not cmd_tpl:
            return None
        # Support "{file}" placeholder; otherwise append quoted path.
        if "{file}" in cmd_tpl:
            cmd = cmd_tpl.replace("{file}", f"\"{file_path}\"")
        else:
            cmd = cmd_tpl + f" \"{file_path}\""

        timeout_s = int(getattr(self.config, "media_upload_timeout_s", 30) or 30)

        def _run() -> str:
            cp = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_s, encoding="utf-8", errors="replace")
            out = (cp.stdout or "").strip()
            if cp.returncode != 0:
                err = (cp.stderr or "").strip()
                raise RuntimeError(f"upload_command failed rc={cp.returncode} stderr={err[:200]}")
            return out

        try:
            out = await asyncio.to_thread(_run)
            # take first http(s) url in stdout
            m = re.search(r"(https?://\\S+)", out)
            return m.group(1) if m else (out if self._is_http_url(out) else None)
        except Exception as e:
            logger.warning("QQ media upload failed: {}", e)
            return None

    async def start(self) -> None:
        """Start the QQ bot."""
        if not QQ_AVAILABLE:
            logger.error("QQ SDK not installed. Run: pip install qq-botpy")
            return

        if not self.config.app_id or not self.config.secret:
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        BotClass = _make_bot_class(self)
        self._client = BotClass()

        logger.info("QQ bot started (C2C private message)")
        await self._run_bot()

    async def _run_bot(self) -> None:
        """Run the bot connection with auto-reconnect."""
        while self._running:
            try:
                await self._client.start(appid=self.config.app_id, secret=self.config.secret)
            except Exception as e:
                logger.warning("QQ bot error: {}", e)
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the QQ bot."""
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        logger.info("QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through QQ."""
        if not self._client:
            logger.warning("QQ client not initialized")
            return
        try:
            # Reply support: if original message_id is provided, QQ API expects msg_seq increasing for same msg_id.
            reply_msg_id = None
            if isinstance(msg.metadata, dict):
                reply_msg_id = str(msg.metadata.get("message_id") or "") or None

            async def _send_text(text: str) -> None:
                if reply_msg_id:
                    seq = self._reply_seq.get(reply_msg_id, 0) + 1
                    self._reply_seq[reply_msg_id] = seq
                    await self._client.api.post_c2c_message(
                        openid=msg.chat_id,
                        msg_type=0,
                        content=text,
                        msg_id=reply_msg_id,
                        msg_seq=seq,
                    )
                else:
                    await self._client.api.post_c2c_message(
                        openid=msg.chat_id,
                        msg_type=0,
                        content=text,
                    )

            # 1) Media (QQ requires public URL)
            for raw in (msg.media or []):
                if not isinstance(raw, str) or not raw.strip():
                    continue
                url = raw.strip()
                if not self._is_http_url(url):
                    if not os.path.isfile(url):
                        await _send_text(f"[media not found] {url}")
                        continue
                    url2 = await self._upload_local_to_public_url(url)
                    if not url2:
                        await _send_text(
                            "QQ 平台发送媒体需要公网 URL。\n"
                            "当前未配置 channels.qq.mediaUploadCommand（用于上传本地文件并输出 URL），因此已降级为仅发送文字提示。\n"
                            f"[local media] {url}"
                        )
                        continue
                    url = url2

                # Try botpy media API (best-effort; may vary by SDK version)
                sent = False
                try:
                    # file_type: 1=image, 2=video, 3=audio(silk). default to image.
                    ext = os.path.splitext(url.split("?", 1)[0])[1].lower()
                    file_type = 1
                    if ext in {".mp4"}:
                        file_type = 2
                    elif ext in {".silk"}:
                        file_type = 3
                    await self._client.api.post_c2c_file(openid=msg.chat_id, file_type=file_type, url=url)
                    sent = True
                except Exception as e:
                    logger.warning("QQ media send failed (will fallback to URL): {}", e)
                if not sent:
                    await _send_text(f"[media url] {url}")

            # 2) Text content
            if msg.content and msg.content.strip():
                await _send_text(msg.content)
        except Exception as e:
            logger.error("Error sending QQ message: {}", e)

    async def _on_message(self, data: "C2CMessage") -> None:
        """Handle incoming message from QQ."""
        try:
            # Dedup by message ID
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            author = data.author
            user_id = str(getattr(author, 'id', None) or getattr(author, 'user_openid', 'unknown'))
            content = (data.content or "").strip()
            media_paths: list[str] = []

            # Attachments (best-effort)
            attachments = getattr(data, "attachments", None)
            if isinstance(attachments, list):
                for a in attachments:
                    if not isinstance(a, dict):
                        continue
                    url = str(a.get("url") or "")
                    fn = str(a.get("filename") or a.get("name") or "")
                    if url:
                        p = await self._download_to_media_dir(url, fn)
                        if p:
                            media_paths.append(p)
                            content += f"\n[attachment: {os.path.basename(p)}]"

            if not content and not media_paths:
                return

            await self._handle_message(
                sender_id=user_id,
                chat_id=user_id,
                content=content,
                media=media_paths,
                metadata={"message_id": data.id},
            )
        except Exception:
            logger.exception("Error handling QQ message")
