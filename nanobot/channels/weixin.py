"""WeChat (微信个人号) channel implementation - rewritten to match weixin-agent-sdk."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from Crypto.Cipher import AES
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from pydantic import Field

# Default API base URL (can be overridden in config)
DEFAULT_BASE_URL = "https://api.weixinbot.io"
DEFAULT_CDN_URL = "https://cdn.weixinbot.io"

# Message type display mapping
MSG_TYPE_MAP = {
    "text": "[text]",
    "image": "[image]",
    "voice": "[voice]",
    "video": "[video]",
    "file": "[file]",
    "mixed": "[mixed content]",
}


class WeixinConfig(Base):
    """WeChat (微信个人号) channel configuration."""

    enabled: bool = False
    account_id: str = "default"  # Account identifier
    base_url: str = DEFAULT_BASE_URL  # API server URL
    bot_token: str = ""  # Login token (auto-filled after login)
    allow_from: list[str] = Field(default_factory=list)
    welcome_message: str = ""
    # Storage directory for account data
    storage_dir: str = ""


class WeixinChannel(BaseChannel):
    """
    WeChat Personal Account channel using long-polling API.
    
    This implementation follows the weixin-agent-sdk approach:
    - QR code login to get bot token
    - Long-polling getUpdates for messages
    - Download media from CDN with AES-128-ECB decryption
    - Checkpoint resume support
    """

    name = "weixin"
    display_name = "WeChat"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WeixinConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = WeixinConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: WeixinConfig = config
        self._running = False
        self._session: requests.Session | None = None
        self._user_id: str | None = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        
        # Storage paths
        self._storage_dir = self._get_storage_dir()
        self._account_file = self._storage_dir / "account.json"
        self._sync_buf_file = self._storage_dir / "sync_buf.txt"
        
        # Load saved account if exists
        self._load_account()

    def _get_storage_dir(self) -> Path:
        """Get storage directory for this account."""
        if self.config.storage_dir:
            return Path(self.config.storage_dir)
        # Default: ~/.nanobot/weixin/{account_id}/
        home = Path.home()
        return home / ".nanobot" / "weixin" / self.config.account_id

    def _load_account(self) -> bool:
        """Load saved account from disk."""
        try:
            if self._account_file.exists():
                data = json.loads(self._account_file.read_text())
                if data.get("bot_token"):
                    self.config.bot_token = data["bot_token"]
                if data.get("base_url"):
                    self.config.base_url = data["base_url"]
                if data.get("user_id"):
                    self._user_id = data["user_id"]
                logger.info("Loaded WeChat account: {}", self.config.account_id)
                return True
        except Exception as e:
            logger.warning("Failed to load account: {}", e)
        return False

    def _save_account(self) -> None:
        """Save account to disk."""
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "account_id": self.config.account_id,
                "bot_token": self.config.bot_token,
                "base_url": self.config.base_url,
                "user_id": self._user_id,
                "cdn_base_url": DEFAULT_CDN_URL,
            }
            self._account_file.write_text(json.dumps(data, indent=2))
            logger.debug("Saved account to {}", self._account_file)
        except Exception as e:
            logger.error("Failed to save account: {}", e)

    def _load_sync_buf(self) -> str:
        """Load sync buffer for checkpoint resume."""
        try:
            if self._sync_buf_file.exists():
                return self._sync_buf_file.read_text()
        except Exception as e:
            logger.warning("Failed to load sync buf: {}", e)
        return ""

    def _save_sync_buf(self, buf: str) -> None:
        """Save sync buffer for checkpoint resume."""
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._sync_buf_file.write_text(buf)
        except Exception as e:
            logger.error("Failed to save sync buf: {}", e)

    async def login(self) -> bool:
        """
        Interactive QR code login.
        Returns True on success.
        """
        logger.info("Starting WeChat QR code login...")
        
        try:
            # Step 1: Get QR code
            qr_resp = self._api_request(
                "/cgi-bin/login/qrcode/start",
                {
                    "bot_type": "ios",  # or "android"
                    "redirect_uri": "https://weixin.qq.com/cgi-bin/logincallback",
                }
            )
            
            if not qr_resp.get("qrcode_url"):
                logger.error("Failed to get QR code: {}", qr_resp.get("message", "Unknown error"))
                return False
            
            # Step 2: Show QR code (print URL for user to scan)
            qr_url = qr_resp["qrcode_url"]
            logger.info("\n" + "=" * 50)
            logger.info("Please scan the QR code with WeChat to login")
            logger.info("QR Code URL: {}", qr_url)
            logger.info("=" * 50 + "\n")
            
            # Step 3: Poll for login result
            session_key = qr_resp.get("session_key")
            for attempt in range(240):  # 4 minutes max
                await asyncio.sleep(1)
                
                poll_resp = self._api_request(
                    "/cgi-bin/login/qrcode/poll",
                    {
                        "session_key": session_key,
                        "timeout": 5000,
                    }
                )
                
                if poll_resp.get("connected"):
                    # Login successful
                    self.config.bot_token = poll_resp["bot_token"]
                    self.config.base_url = poll_resp.get("base_url", self.config.base_url)
                    self._user_id = poll_resp.get("user_id")
                    
                    self._save_account()
                    logger.info("WeChat login successful! User ID: {}", self._user_id)
                    return True
                
                if poll_resp.get("errcode") == -4:
                    # Still waiting for scan
                    continue
                elif poll_resp.get("errcode") == -5:
                    # Scanned but not confirmed
                    logger.info("QR code scanned, please confirm on phone")
                    continue
                elif poll_resp.get("errcode") == -6:
                    # Wrong QR code, need new one
                    logger.warning("QR code expired, requesting new one...")
                    break
                else:
                    logger.warning("Login poll: {}", poll_resp)
            
            logger.error("Login timeout")
            return False
            
        except Exception as e:
            logger.error("Login failed: {}", e)
            return False

    def _api_request(self, endpoint: str, data: dict | None = None) -> dict:
        """Make API request to WeChat backend."""
        url = urljoin(self.config.base_url, endpoint)
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.bot_token}" if self.config.bot_token else "",
        }
        
        try:
            resp = requests.post(
                url,
                json=data or {},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("API request failed: {}", e)
            return {"errcode": -1, "message": str(e)}

    async def start(self) -> None:
        """Start the WeChat bot with long-polling."""
        self._running = True
        self._session = requests.Session()
        
        # Check if we have a token
        if not self.config.bot_token:
            logger.warning("No bot token found. Please run login first.")
            # Try to load from saved account
            if not self._load_account():
                logger.error("No saved account found. Please login first.")
                return
        
        logger.info("WeChat bot starting (account: {})", self.config.account_id)
        
        # Load sync buffer for checkpoint resume
        sync_buf = self._load_sync_buf()
        if sync_buf:
            logger.info("Resuming from previous sync buffer ({} bytes)", len(sync_buf))
        
        # Long-polling loop
        while self._running:
            try:
                resp = await self._get_updates(sync_buf)
                
                if "errcode" in resp and resp["errcode"] != 0:
                    if resp["errcode"] == -14:  # Session expired
                        logger.warning("Session expired, waiting 1 hour before retry...")
                        await asyncio.sleep(3600)
                        continue
                    logger.error("getUpdates error: {}", resp)
                    await asyncio.sleep(30)
                    continue
                
                # Save sync buffer
                if resp.get("get_updates_buf"):
                    sync_buf = resp["get_updates_buf"]
                    self._save_sync_buf(sync_buf)
                
                # Process messages
                msgs = resp.get("msgs", [])
                for msg in msgs:
                    await self._process_message(msg)
                    
            except Exception as e:
                logger.error("Error in getUpdates loop: {}", e)
                await asyncio.sleep(30)

    async def stop(self) -> None:
        """Stop the WeChat bot."""
        self._running = False
        if self._session:
            self._session.close()
        logger.info("WeChat bot stopped")

    async def _get_updates(self, sync_buf: str = "") -> dict:
        """Long-poll for new messages."""
        url = urljoin(self.config.base_url, "/cgi-bin/message/get_updates")
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.bot_token}",
        }
        
        data = {
            "get_updates_buf": sync_buf,
            "timeout_ms": 35000,  # 35 seconds
        }
        
        try:
            # Use asyncio to avoid blocking
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: requests.post(url, json=data, headers=headers, timeout=40)
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("getUpdates request failed: {}", e)
            return {"errcode": -1, "message": str(e)}

    async def _process_message(self, msg: dict) -> None:
        """Process incoming message and forward to bus."""
        try:
            msg_id = msg.get("msg_id", "")
            if not msg_id:
                msg_id = f"{msg.get('from_user_id', '')}_{msg.get('create_time', '')}"
            
            # Deduplication
            if msg_id in self._processed_message_ids:
                return
            self._processed_message_ids[msg_id] = None
            
            # Trim cache
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)
            
            from_user_id = msg.get("from_user_id", "")
            item_list = msg.get("item_list", [])
            
            content_parts = []
            media = None
            
            for item in item_list:
                item_type = item.get("type", "")
                
                if item_type == "text":
                    text = item.get("text", {}).get("content", "")
                    if text:
                        content_parts.append(text)
                        
                elif item_type == "image":
                    image_data = item.get("image", {})
                    file_path = await self._download_media(
                        image_data.get("url", ""),
                        image_data.get("aes_key", ""),
                        "image"
                    )
                    if file_path:
                        content_parts.append("[image]")
                        media = [file_path]
                    else:
                        content_parts.append("[image: download failed]")
                        
                elif item_type == "voice":
                    voice_data = item.get("voice", {})
                    # Voice may have transcription
                    content = voice_data.get("content", "")
                    if content:
                        content_parts.append(f"[voice] {content}")
                    else:
                        content_parts.append("[voice]")
                        
                elif item_type == "video":
                    video_data = item.get("video", {})
                    file_path = await self._download_media(
                        video_data.get("url", ""),
                        video_data.get("aes_key", ""),
                        "video"
                    )
                    if file_path:
                        content_parts.append("[video]")
                        media = [file_path]
                    else:
                        content_parts.append("[video: download failed]")
                        
                elif item_type == "file":
                    file_data = item.get("file", {})
                    file_path = await self._download_media(
                        file_data.get("url", ""),
                        file_data.get("aes_key", ""),
                        "file",
                        file_data.get("name", "file")
                    )
                    if file_path:
                        content_parts.append(f"[file: {file_data.get('name', 'file')}]")
                        media = [file_path]
                    else:
                        content_parts.append(f"[file: download failed]")
                        
                else:
                    content_parts.append(MSG_TYPE_MAP.get(item_type, f"[{item_type}]"))
            
            content = "\n".join(content_parts)
            if not content:
                return
            
            # Forward to message bus
            await self._handle_message(
                sender_id=from_user_id,
                chat_id=from_user_id,
                content=content,
                media=media,
                metadata={
                    "message_id": msg_id,
                    "account_id": self.config.account_id,
                }
            )
            
        except Exception as e:
            logger.error("Error processing message: {}", e)

    async def _download_media(
        self, 
        url: str, 
        aes_key: str, 
        media_type: str, 
        filename: str | None = None
    ) -> str | None:
        """Download media from CDN and decrypt with AES-128-ECB."""
        if not url or not aes_key:
            return None
            
        try:
            # Download encrypted data
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            encrypted_data = resp.content
            
            # Decrypt with AES-128-ECB
            cipher = AES.new(aes_key.encode()[:16], AES.MODE_ECB)
            decrypted_data = cipher.decrypt(encrypted_data)
            
            # Remove PKCS7 padding
            padding_len = decrypted_data[-1]
            decrypted_data = decrypted_data[:-padding_len]
            
            # Save to file
            media_dir = get_media_dir("weixin")
            media_dir.mkdir(parents=True, exist_ok=True)
            
            if not filename:
                ext = {
                    "image": ".jpg",
                    "voice": ".silk",
                    "video": ".mp4",
                    "file": "",
                }.get(media_type, "")
                filename = f"{media_type}_{hash(url) % 100000}{ext}"
            
            file_path = media_dir / filename
            file_path.write_bytes(decrypted_data)
            
            logger.debug("Downloaded {} to {}", media_type, file_path)
            return str(file_path)
            
        except Exception as e:
            logger.error("Error downloading media: {}", e)
            return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through WeChat."""
        if not self.config.bot_token:
            logger.warning("No bot token, cannot send message")
            return
            
        try:
            content = msg.content.strip()
            if not content:
                return
            
            # Prepare message data
            data = {
                "to_user": msg.chat_id,
                "msg_type": "text",
                "content": content,
            }
            
            # Handle media if present
            if msg.media:
                # TODO: Implement media upload and sending
                logger.warning("Media sending not yet implemented")
            
            resp = self._api_request("/cgi-bin/message/send", data)
            
            if resp.get("errcode") == 0:
                logger.debug("WeChat message sent to {}", msg.chat_id)
            else:
                logger.error("Failed to send message: {}", resp)
                
        except Exception as e:
            logger.error("Error sending WeChat message: {}", e)


# CLI commands for login
async def login_command(account_id: str = "default") -> bool:
    """CLI command to login to WeChat."""
    config = WeixinConfig(account_id=account_id)
    channel = WeixinChannel(config, bus=None)
    return await channel.login()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        account_id = sys.argv[2] if len(sys.argv) > 2 else "default"
        success = asyncio.run(login_command(account_id))
        sys.exit(0 if success else 1)
    else:
        print("Usage: python -m nanobot.channels.weixin login [account_id]")
        sys.exit(1)