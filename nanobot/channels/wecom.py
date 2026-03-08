"""Enterprise WeChat (WeCom) channel implementation."""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import threading
import time
from collections import OrderedDict
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from Crypto.Cipher import AES
from flask import Flask, request, Response
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WeComConfig


class WeComCrypto:
    """Enterprise WeChat message encryption/decryption utility."""
    
    def __init__(self, token: str, encoding_aes_key: str, corp_id: str):
        self.token = token
        self.corp_id = corp_id
        
        try:
            self.aes_key = base64.b64decode(encoding_aes_key + "=")
        except Exception as e:
            raise ValueError(f"Invalid encoding_aes_key: {e}")
        
        if len(self.aes_key) != 32:
            raise ValueError("AES key must be 32 bytes")
    
    def _generate_random_string(self, length: int = 16) -> bytes:
        return os.urandom(length)
    
    def _pkcs7_pad(self, data: bytes, block_size: int = 32) -> bytes:
        pad_len = block_size - (len(data) % block_size)
        return data + bytes([pad_len] * pad_len)
    
    def _pkcs7_unpad(self, data: bytes) -> bytes:
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 32:
            raise ValueError("Invalid padding")
        return data[:-pad_len]
    
    def encrypt(self, text: str) -> tuple[str, str, str, str]:
        """Encrypt message for sending to WeCom."""
        random_str = self._generate_random_string(16)
        msg_bytes = text.encode("utf-8")
        msg_len = struct.pack(">I", len(msg_bytes))
        to_encrypt = random_str + msg_len + msg_bytes + self.corp_id.encode("utf-8")
        
        padded = self._pkcs7_pad(to_encrypt)
        iv = self.aes_key[:16]
        cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(padded)
        encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")
        
        timestamp = str(int(time.time()))
        nonce = self._generate_random_string(8).hex()
        signature = self._compute_signature(self.token, timestamp, nonce, encrypted_b64)
        
        return encrypted_b64, signature, timestamp, nonce
    
    def decrypt(self, encrypted_text: str) -> str:
        """Decrypt message received from WeCom."""
        try:
            encrypted = base64.b64decode(encrypted_text)
            iv = self.aes_key[:16]
            cipher = AES.new(self.aes_key, AES.MODE_CBC, iv)
            decrypted = cipher.decrypt(encrypted)
            unpadded = self._pkcs7_unpad(decrypted)
            
            msg_len = struct.unpack(">I", unpadded[16:20])[0]
            msg = unpadded[20:20 + msg_len]
            
            corp_id_bytes = unpadded[20 + msg_len:]
            if corp_id_bytes.decode("utf-8") != self.corp_id:
                raise ValueError("CorpID mismatch")
            
            return msg.decode("utf-8")
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")
    
    def _compute_signature(self, token: str, timestamp: str, nonce: str, encrypted: str) -> str:
        data = "".join(sorted([token, timestamp, nonce, encrypted]))
        return hashlib.sha1(data.encode("utf-8")).hexdigest()
    
    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypted: str) -> bool:
        expected = self._compute_signature(self.token, timestamp, nonce, encrypted)
        return hmac.compare_digest(msg_signature, expected)
    
    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echo_str: str) -> str:
        """Verify URL during WeCom app setup."""
        if not self.verify_signature(msg_signature, timestamp, nonce, echo_str):
            raise ValueError("Invalid signature")
        return self.decrypt(echo_str)


def parse_xml(xml_data: str) -> dict[str, Any]:
    """Parse WeCom XML message."""
    try:
        root = ET.fromstring(xml_data)
        
        msg: dict[str, Any] = {
            "to_agent": root.findtext("ToAgent", ""),
            "from_user": root.findtext("FromUserName", ""),
            "create_time": int(root.findtext("CreateTime", "0")),
            "msg_type": root.findtext("MsgType", ""),
            "msg_id": root.findtext("MsgId", ""),
        }
        
        if msg["msg_type"] == "text":
            msg["content"] = root.findtext("Content", "")
        elif msg["msg_type"] == "image":
            msg["pic_url"] = root.findtext("PicUrl", "")
            msg["media_id"] = root.findtext("MediaId", "")
        elif msg["msg_type"] == "event":
            msg["event"] = root.findtext("Event", "")
            msg["event_key"] = root.findtext("EventKey", "")
        
        return msg
    except ET.ParseError as e:
        logger.error("XML parse error: {}", e)
        return {}


class WeComChannel(BaseChannel):
    """
    Enterprise WeChat channel using webhook callback.
    
    Requires:
    - CorpID, AgentID, CorpSecret from WeCom admin
    - Token and EncodingAESKey from app callback settings
    - Public IP or accessible server for webhook
    """
    
    name = "wecom"
    
    def __init__(self, config: WeComConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WeComConfig = config
        self._access_token: str | None = None
        self._token_expiry: float = 0
        self._http: httpx.AsyncClient | None = None
        self._crypto: WeComCrypto | None = None
        self._flask_app: Flask | None = None
        self._flask_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self.api_base = config.api_base or "https://qyapi.weixin.qq.com/cgi-bin"
        self._connected = False
        self._callback_server_running = False
    
    async def start(self) -> None:
        """Start the WeCom channel."""
        if not self.config.corp_id or not self.config.corp_secret:
            logger.error("WeCom corp_id and corp_secret not configured")
            return
        
        if not self.config.agent_id:
            logger.error("WeCom agent_id not configured")
            return
        
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._http = httpx.AsyncClient(timeout=30.0)
        
        if self.config.token and self.config.encoding_aes_key:
            try:
                self._crypto = WeComCrypto(
                    self.config.token,
                    self.config.encoding_aes_key,
                    self.config.corp_id
                )
                logger.info("WeCom message encryption enabled")
            except Exception as e:
                logger.error("Failed to initialize WeCom crypto: {}", e)
        
        await self._refresh_access_token()
        await self._start_callback_server()
        
        logger.info("WeCom channel started")
        logger.info("Callback URL: http://0.0.0.0:{}{}", self.config.callback_port, self.config.callback_path)
        
        while self._running:
            await asyncio.sleep(1)
            if time.time() > self._token_expiry - 300:
                await self._refresh_access_token()
            if not self._callback_server_running:
                logger.warning("WeCom callback server stopped, restarting...")
                await self._start_callback_server()
    
    async def stop(self) -> None:
        """Stop the WeCom channel."""
        self._running = False
        self._connected = False
        self._callback_server_running = False
        if self._http:
            await self._http.aclose()
        logger.info("WeCom channel stopped")
    
    async def _refresh_access_token(self) -> None:
        """Refresh access token from WeCom."""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                url = f"{self.api_base}/gettoken"
                params = {"corpid": self.config.corp_id, "corpsecret": self.config.corp_secret}
                
                response = await self._http.get(url, params=params)
                data = response.json()
                
                if data.get("errcode") == 0:
                    self._access_token = data["access_token"]
                    expires_in = data.get("expires_in", 7200)
                    self._token_expiry = time.time() + expires_in - 300
                    self._connected = True
                    logger.debug("WeCom access token refreshed (expires in {}s)", expires_in)
                    return
                else:
                    logger.error("Failed to get access token: {}", data)
            except Exception as e:
                logger.error("Error refreshing access token (attempt {}/{}): {}", attempt + 1, max_retries, e)
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
        
        self._connected = False
    
    async def _start_callback_server(self) -> None:
        """Start Flask server for receiving WeCom callbacks."""
        self._flask_app = Flask(__name__)
        self._flask_app.logger.setLevel(logging.WARNING)
        
        @self._flask_app.route(self.config.callback_path, methods=['GET', 'POST'])
        def callback():
            return self._handle_callback()
        
        def run_flask():
            try:
                self._callback_server_running = True
                self._flask_app.run(host='0.0.0.0', port=self.config.callback_port, threaded=True, debug=False, use_reloader=False)
            except Exception as e:
                logger.error("Flask server error: {}", e)
                self._callback_server_running = False
        
        self._flask_thread = threading.Thread(target=run_flask, daemon=True)
        self._flask_thread.start()
        await asyncio.sleep(0.5)
    
    def _handle_callback(self) -> Response:
        """Handle WeCom callback."""
        msg_signature = request.args.get('msg_signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')
        
        if request.method == 'GET':
            if not echostr or not self._crypto:
                return Response("Invalid config", status=400)
            try:
                decrypted = self._crypto.verify_url(msg_signature, timestamp, nonce, echostr)
                logger.info("WeCom URL verification successful")
                return Response(decrypted)
            except Exception as e:
                logger.error("URL verification failed: {}", e)
                return Response("Verification failed", status=400)
        
        if request.method == 'POST':
            try:
                encrypted_msg = request.data.decode('utf-8')
                
                if self._crypto:
                    if not self._crypto.verify_signature(msg_signature, timestamp, nonce, encrypted_msg):
                        logger.warning("Invalid message signature")
                        return Response("Invalid signature", status=400)
                    decrypted = self._crypto.decrypt(encrypted_msg)
                else:
                    decrypted = encrypted_msg
                
                msg_data = parse_xml(decrypted)
                
                if self._loop and self._loop.is_running():
                    asyncio.run_coroutine_threadsafe(self._handle_inbound_message(msg_data), self._loop)
                
                return Response("success")
            except Exception as e:
                logger.error("Error processing callback: {}", e)
                return Response("Error", status=500)
        
        return Response("Method not allowed", status=405)
    
    async def _handle_inbound_message(self, msg_data: dict[str, Any]) -> None:
        """Process inbound message from WeCom."""
        try:
            msg_id = msg_data.get("msg_id", "")
            if msg_id:
                if msg_id in self._processed_message_ids:
                    logger.debug("Duplicate message ignored: {}", msg_id)
                    return
                self._processed_message_ids[msg_id] = None
                while len(self._processed_message_ids) > 1000:
                    self._processed_message_ids.popitem(last=False)
            
            from_user = msg_data.get("from_user", "")
            msg_type = msg_data.get("msg_type", "")
            content = msg_data.get("content", "")
            
            if msg_type != "text":
                logger.debug("Skipping non-text message type: {}", msg_type)
                return
            
            if not content or not content.strip():
                return
            
            if not self.is_allowed(from_user):
                logger.warning("Access denied for user: {}", from_user)
                return
            
            await self._handle_message(
                sender_id=from_user,
                chat_id=from_user,
                content=content,
                metadata={"msg_id": msg_id, "msg_type": msg_type}
            )
        except Exception as e:
            logger.error("Error handling inbound message: {}", e)
    
    async def send(self, msg: OutboundMessage) -> None:
        """Send message through WeCom."""
        if not self._access_token or not self._connected:
            logger.warning("WeCom access token not available")
            return
        
        try:
            receive_id = msg.chat_id
            
            if msg.media:
                logger.warning("WeCom media sending not yet implemented")
            
            if msg.content and msg.content.strip():
                is_markdown = self._is_markdown(msg.content)
                if is_markdown:
                    await self._send_markdown(receive_id, msg.content)
                else:
                    await self._send_text(receive_id, msg.content)
        except Exception as e:
            logger.error("Error sending WeCom message: {}", e)
    
    def _is_markdown(self, text: str) -> bool:
        markdown_indicators = ["**", "```", "# ", "- ", "* ", "1. ", "[", "](", "![", "|"]
        return any(indicator in text for indicator in markdown_indicators)
    
    async def _send_text(self, user_id: str, content: str) -> None:
        """Send text message."""
        url = f"{self.api_base}/message/send"
        params = {"access_token": self._access_token}
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": self.config.agent_id,
            "text": {"content": content},
            "safe": 0
        }
        
        response = await self._http.post(url, params=params, json=payload)
        data = response.json()
        
        if data.get("errcode") == 0:
            logger.debug("WeCom text message sent to {}", user_id)
        else:
            logger.error("Failed to send WeCom text message: {}", data)
            if data.get("errcode") == 40014:
                await self._refresh_access_token()
    
    async def _send_markdown(self, user_id: str, content: str) -> None:
        """Send markdown message."""
        url = f"{self.api_base}/message/send"
        params = {"access_token": self._access_token}
        payload = {
            "touser": user_id,
            "msgtype": "markdown",
            "agentid": self.config.agent_id,
            "markdown": {"content": content}
        }
        
        response = await self._http.post(url, params=params, json=payload)
        data = response.json()
        
        if data.get("errcode") == 0:
            logger.debug("WeCom markdown message sent to {}", user_id)
        else:
            logger.error("Failed to send WeCom markdown message: {}", data)
            if data.get("errcode") == 40014:
                await self._refresh_access_token()


__all__ = ["WeComChannel", "WeComCrypto", "parse_xml"]
