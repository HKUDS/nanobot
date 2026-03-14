"""WeCom (Enterprise WeChat) App channel implementation using wecom_app_svr."""

import asyncio
import os
import threading
import time
from typing import Any

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WecomAppConfig
from nanobot.config.paths import get_media_dir

# Try to import wecom_app_svr
try:
    from wecom_app_svr import WecomAppServer, RspTextMsg
    WECOM_APP_AVAILABLE = True
except ImportError:
    WECOM_APP_AVAILABLE = False
    RspTextMsg = None


class WecomAppChannel(BaseChannel):
    """WeCom (Enterprise WeChat) App channel using webhook server."""

    name = "wecom_app"
    display_name = "WeCom App"

    def __init__(self, config: WecomAppConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WecomAppConfig = config
        self._server: Any = None
        self._processed_message_ids: dict[str, None] = {}
        self._chat_frames: dict[str, Any] = {}
        # Note: httpx clients are created fresh for each request to avoid event loop issues
        self._access_token: str | None = None
        self._token_expiry: float = 0
        self._background_tasks: set[asyncio.Task] = set()
        self._token_lock: asyncio.Lock | None = None
        self._media_dir: str | None = None

    async def start(self) -> None:
        """Start the WeCom App bot server."""
        if not WECOM_APP_AVAILABLE:
            logger.error("wecom_app_svr not installed. Run: pip install wecom-app-svr")
            return

        if not self.config.token or not self.config.aes_key or not self.config.corp_id:
            logger.error("WeCom App token, aes_key, and corp_id not configured")
            return

        self._token_lock = asyncio.Lock()
        self._running = True
        self._media_dir = get_media_dir("wecom_app")

        self._server = WecomAppServer(
            "nanobot-wecom-app",
            self.config.host or "0.0.0.0",
            self.config.port,
            path=self.config.path or "/wecom_app",
            token=self.config.token,
            aes_key=self.config.aes_key,
            corp_id=self.config.corp_id,
        )

        self._server.set_message_handler(self._msg_handler)
        self._server.set_event_handler(self._event_handler)

        logger.info("WeCom App server starting on {}:{}{}", 
            self.config.host or "0.0.0.0", 
            self.config.port,
            self.config.path or "/wecom_app")

        # Run Flask server in a separate thread to avoid blocking the event loop
        # This allows the dispatcher to continue processing outbound messages
        self._server_thread = threading.Thread(target=self._server.run, daemon=True)
        self._server_thread.start()

        # Wait for server to start
        await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the WeCom App bot."""
        self._running = False
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()
        logger.info("WeCom App bot stopped")

    def _msg_handler(self, req_msg: Any) -> Any:
        """Handle incoming messages - synchronous, returns immediately."""
        if not WECOM_APP_AVAILABLE or RspTextMsg is None:
            return self._create_default_response()

        try:
            msg_type = getattr(req_msg, 'msg_type', 'unknown')
            msg_id = getattr(req_msg, 'msg_id', f"{msg_type}_{getattr(req_msg, 'content', '')}")

            if msg_id in self._processed_message_ids:
                return RspTextMsg()
            self._processed_message_ids[msg_id] = None

            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.pop(next(iter(self._processed_message_ids)))

            sender_id = getattr(req_msg, 'from_user', 'unknown')
            chat_id = getattr(req_msg, 'chat_id', sender_id)

            logger.info(f"WeCom App: sender_id={sender_id}, chat_id={chat_id}, msg_type={msg_type}")

            self._chat_frames[chat_id] = req_msg

            # Create background task for async processing
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    task = loop.create_task(self._handle_message_async(req_msg))
                    task.add_done_callback(self._background_tasks.discard)
                    self._background_tasks.add(task)
                else:
                    asyncio.run(self._handle_message_async(req_msg))
            except RuntimeError:
                asyncio.run(self._handle_message_async(req_msg))

            # Return immediate confirmation
            ret = RspTextMsg()
            # ret.content = "消息已收到，正在处理中..."
            return ret

        except Exception as e:
            logger.error("Error in WeCom App message handler: {}", e)
            return self._create_default_response()

    def _event_handler(self, req_msg: Any) -> Any:
        """Handle incoming events - synchronous, returns immediately."""
        if not WECOM_APP_AVAILABLE or RspTextMsg is None:
            return self._create_default_response()

        try:
            event_type = getattr(req_msg, 'event_type', 'unknown')
            sender_id = getattr(req_msg, 'from_user', 'unknown')
            chat_id = getattr(req_msg, 'chat_id', sender_id)

            logger.info(f"WeCom App event: event_type={event_type}, chat_id={chat_id}")

            self._chat_frames[chat_id] = req_msg

            if event_type == 'add_to_chat':
                content = self.config.welcome_message or "欢迎！我是您的 AI 助手。"
                ret = RspTextMsg()
                ret.content = content
                return ret

            ret = RspTextMsg()
            ret.content = f"事件已收到: {event_type}"
            return ret

        except Exception as e:
            logger.error("Error in WeCom App event handler: {}", e)
            return self._create_default_response()

    def _create_default_response(self) -> Any:
        """Create default response."""
        if RspTextMsg is None:
            return None
        ret = RspTextMsg()
        ret.content = "OK"
        return ret

    async def _handle_message_async(self, req_msg: Any) -> None:
        """Handle incoming message asynchronously."""
        try:
            msg_type = getattr(req_msg, 'msg_type', 'unknown')
            sender_id = getattr(req_msg, 'from_user', 'unknown')
            chat_id = getattr(req_msg, 'chat_id', sender_id)

            content = ""
            media = None

            if msg_type == 'text':
                content = getattr(req_msg, 'content', '')
            elif msg_type == 'image':
                media_id = getattr(req_msg, 'media_id', '')
                # Download image and save locally
                file_path = await self._download_media(media_id, "image") if media_id else None
                if file_path:
                    content = f"[image: {os.path.basename(file_path)}]"
                    media = [file_path]
                else:
                    content = "[image]"
                    media = None
            elif msg_type == 'video':
                media_id = getattr(req_msg, 'media_id', '')
                # Download video and save locally
                file_path = await self._download_media(media_id, "video") if media_id else None
                if file_path:
                    content = f"[video: {os.path.basename(file_path)}]"
                    media = [file_path]
                else:
                    content = "[video]"
                    media = None
            elif msg_type == 'voice':
                media_id = getattr(req_msg, 'media_id', '')
                # Download voice and save locally
                file_path = await self._download_media(media_id, "voice") if media_id else None
                if file_path:
                    content = f"[voice: {os.path.basename(file_path)}]"
                    media = [file_path]
                else:
                    content = "[voice]"
                    media = None
            else:
                content = f"msg_type: {msg_type}"

            if not content:
                content = f"msg_type: {msg_type}"

            logger.info(f"WeCom App processing: content={content[:50]}...")

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=media,
                metadata={
                    "msg_type": msg_type,
                    "media_id": getattr(req_msg, 'media_id', ''),
                }
            )

            logger.info("WeCom App message forwarded to bus")

        except Exception as e:
            logger.error("Error in async message handling: {}", e)


    async def _download_media(self, media_id: str, media_type: str) -> str | None:
        """Download media from WeCom API and save to local file."""
        if not media_id:
            return None

        token = await self._get_access_token()
        if not token:
            return None

        # Create a fresh httpx client for this request to avoid event loop issues
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                url = f"https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={media_id}"
                resp = await client.get(url)

                # Check if response is JSON (error) or binary (success)
                content_type = resp.headers.get("content-type", "")

                if "application/json" in content_type:
                    data = resp.json()
                    if data.get("errcode") != 0:
                        logger.error("WeCom App download media failed: {}", data.get("errmsg"))
                        return None

                # Determine filename from headers or generate one
                content_disposition = resp.headers.get("content-disposition", "")
                if "filename=" in content_disposition:
                    # Extract filename from content-disposition header
                    import re
                    match = re.search(r'filename="?([^";]+)"?', content_disposition)
                    if match:
                        filename = match.group(1)
                    else:
                        filename = None
                else:
                    filename = None

                if not filename:
                    ext = ".jpg" if media_type == "image" else ".mp4" if media_type == "video" else ".amr"
                    filename = f"{media_type}_{media_id[:16]}{ext}"

                # Ensure media directory exists
                os.makedirs(self._media_dir, exist_ok=True)

                # Save file
                file_path = os.path.join(self._media_dir, filename)
                with open(file_path, "wb") as f:
                    f.write(resp.content)

                logger.info("WeCom App downloaded {} to {}", media_type, file_path)
                return file_path

            except Exception as e:
                logger.error("Error downloading WeCom App media: {}", e)
                return None

    async def _get_access_token(self) -> str | None:
        """Get or refresh Access Token for WeCom API."""
        # Return cached token if valid
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        # Check if we have credentials
        agent_id = getattr(self.config, 'agentid', None)
        secret = getattr(self.config, 'secret', None)

        if not agent_id:
            logger.warning("WeCom App agent_id not configured")
            return None
        if not secret:
            logger.warning("WeCom App secret not configured")
            return None

        # Use lock to prevent concurrent token refreshes
        if self._token_lock:
            async with self._token_lock:
                # Double-check after acquiring lock
                if self._access_token and time.time() < self._token_expiry:
                    return self._access_token

                # Use fresh httpx client to avoid event loop issues
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.config.corp_id}&corpsecret={secret}"
                        resp = await client.get(url)
                        resp.raise_for_status()
                        data = resp.json()

                        if data.get("errcode") != 0:
                            logger.error("WeCom App gettoken failed: {}", data.get("errmsg"))
                            return None

                        self._access_token = data.get("access_token")
                        expires_in = data.get("expires_in", 7200)
                        self._token_expiry = time.time() + expires_in - 60

                        logger.info("WeCom App access token refreshed")
                        return self._access_token

                except Exception as e:
                    logger.error("Error getting WeCom App access token: {}", e)
                    return None
        else:
            # Fallback if lock not initialized - use fresh client
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.config.corp_id}&corpsecret={secret}"
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("errcode") != 0:
                        logger.error("WeCom App gettoken failed: {}", data.get("errmsg"))
                        return None

                    self._access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 7200)
                    self._token_expiry = time.time() + expires_in - 60

                    logger.info("WeCom App access token refreshed")
                    return self._access_token

            except Exception as e:
                logger.error("Error getting WeCom App access token: {}", e)
                return None

    async def _send_via_api(self, user_id: str, content: str) -> bool:
        """Send message via WeCom API."""
        token = await self._get_access_token()
        if not token:
            return False

        # Create a fresh httpx client for this request to avoid event loop issues
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"

                payload = {
                    "touser": user_id,
                    "msgtype": "text",
                    "agentid": getattr(self.config, 'agentid', ''),
                    "text": {"content": content}
                }

                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()

                if data.get("errcode") != 0:
                    logger.error("WeCom App send failed: {}", data.get("errmsg"))
                    return False

                logger.info("WeCom App message sent via API to {}", user_id)
                return True

            except Exception as e:
                logger.error("Error sending WeCom App message via API: {}", e)
                return False

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WeCom App."""
        try:
            content = msg.content.strip()
            if not content:
                return

            # Check if we have API credentials
            agent_id = getattr(self.config, 'agentid', None)
            secret = getattr(self.config, 'secret', None)

            if agent_id and secret:
                user_id = msg.chat_id
                success = await self._send_via_api(user_id, content)
                if success:
                    logger.info("WeCom App message sent to {}", msg.chat_id)
                else:
                    logger.warning("Failed to send WeCom App message to {}", msg.chat_id)
            else:
                logger.warning(
                    "WeCom App agent_id/secret not configured. "
                    "Cannot send proactive messages."
                )

        except Exception as e:
            logger.error("Error sending WeCom App message: {}", e)
