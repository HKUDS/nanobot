"""DingTalk/DingDing channel implementation using Stream Mode."""

import asyncio
import json
import threading
import time
from typing import Any

from loguru import logger
import httpx

from nanobot.bus.events import OutboundMessage, InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DingTalkConfig

try:
    from dingtalk_stream import (
        DingTalkStreamClient, 
        Credential,
        CallbackHandler,
        CallbackMessage,
        AckMessage
    )
    from dingtalk_stream.chatbot import ChatbotMessage
    DINGTALK_AVAILABLE = True
except ImportError:
    DINGTALK_AVAILABLE = False


class NanobotDingTalkHandler(CallbackHandler):
    """
    Standard DingTalk Stream SDK Callback Handler.
    Parses incoming messages and forwards them to the Nanobot channel.
    """
    def __init__(self, channel: "DingTalkChannel"):
        super().__init__()
        self.channel = channel
        
    async def process(self, message: CallbackMessage):
        """Process incoming stream message."""
        try:
            # Parse using SDK's ChatbotMessage for robust handling
            chatbot_msg = ChatbotMessage.from_dict(message.data)
            
            # Extract content based on message type
            content = ""
            if chatbot_msg.text:
                content = chatbot_msg.text.content.strip()
            elif chatbot_msg.message_type == "text":
                 # Fallback manual extraction if object not populated
                 content = message.data.get("text", {}).get("content", "").strip()
            
            if not content:
                logger.warning(f"Received empty or unsupported message type: {chatbot_msg.message_type}")
                return AckMessage.STATUS_OK, "OK"

            sender_id = chatbot_msg.sender_staff_id or chatbot_msg.sender_id
            sender_name = chatbot_msg.sender_nick or "Unknown"
            
            logger.info(f"Received DingTalk message from {sender_name} ({sender_id}): {content}")

            # Forward to Nanobot
            # We use asyncio.create_task to avoid blocking the ACK return
            asyncio.create_task(
                self.channel._on_message(content, sender_id, sender_name)
            )

            return AckMessage.STATUS_OK, "OK"
            
        except Exception as e:
            logger.error(f"Error processing DingTalk message: {e}")
            # Return OK to avoid retry loop from DingTalk server if it's a parsing error
            return AckMessage.STATUS_OK, "Error"

class DingTalkChannel(BaseChannel):
    """
    DingTalk channel using Stream Mode.
    
    Uses WebSocket to receive events via `dingtalk-stream` SDK.
    Uses direct HTTP API to send messages (since SDK is mainly for receiving).
    """
    
    name = "dingtalk"
    
    def __init__(self, config: DingTalkConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: DingTalkConfig = config
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        
        # Access Token management for sending messages
        self._access_token: str | None = None
        self._token_expiry: float = 0
    
    async def start(self) -> None:
        """Start the DingTalk bot with Stream Mode."""
        try:
            if not DINGTALK_AVAILABLE:
                logger.error("DingTalk Stream SDK not installed. Run: pip install dingtalk-stream")
                return
            
            if not self.config.client_id or not self.config.client_secret:
                logger.error("DingTalk client_id and client_secret not configured")
                return
                
            self._running = True
            self._loop = asyncio.get_running_loop()
            
            logger.info(f"Initializing DingTalk Stream Client with Client ID: {self.config.client_id}...")
            credential = Credential(self.config.client_id, self.config.client_secret)
            self._client = DingTalkStreamClient(credential)
            
            # Register standard handler
            handler = NanobotDingTalkHandler(self)
            
            # Register using the chatbot topic standard for bots
            self._client.register_callback_handler(
                ChatbotMessage.TOPIC,
                handler
            )
            
            logger.info("DingTalk bot started with Stream Mode")
            
            # The client.start() method is an async infinite loop that handles the websocket connection
            await self._client.start()

        except Exception as e:
            logger.exception(f"Failed to start DingTalk channel: {e}")
            
    async def stop(self) -> None:
        """Stop the DingTalk bot."""
        self._running = False
        # SDK doesn't expose a clean stop method that cancels loop immediately without private access
        pass

    async def _get_access_token(self) -> str | None:
        """Get or refresh Access Token."""
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token
            
        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        data = {
            "appKey": self.config.client_id,
            "appSecret": self.config.client_secret
        }
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=data)
                resp.raise_for_status()
                res_data = resp.json()
                self._access_token = res_data.get("accessToken")
                # Expire 60s early to be safe
                self._token_expiry = time.time() + int(res_data.get("expireIn", 7200)) - 60
                return self._access_token
        except Exception as e:
            logger.error(f"Failed to get DingTalk access token: {e}")
            return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through DingTalk."""
        token = await self._get_access_token()
        if not token:
            return
            
        # This endpoint is for sending to a single user in a bot chat
        # https://open.dingtalk.com/document/orgapp/robot-batch-send-messages
        url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
        
        headers = {
            "x-acs-dingtalk-access-token": token
        }
        
        # Convert markdown code blocks for basic compatibility if needed, 
        # but DingTalk supports markdown loosely.
        
        data = {
            "robotCode": self.config.client_id,
            "userIds": [msg.chat_id],  # chat_id is the user's staffId/unionId
            "msgKey": "sampleMarkdown", # Using markdown template
            "msgParam": json.dumps({
                "text": msg.content,
                "title": "Nanobot Reply" 
            })
        }
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=data, headers=headers)
                # Check 200 OK but also API error codes if any
                if resp.status_code != 200:
                    logger.error(f"DingTalk send failed: {resp.text}")
                else:
                    logger.debug(f"DingTalk message sent to {msg.chat_id}")
        except Exception as e:
            logger.error(f"Error sending DingTalk message: {e}")

    async def _on_message(self, content: str, sender_id: str, sender_name: str) -> None:
        """Handle incoming message (called by NanobotDingTalkHandler)."""
        try:
            logger.info(f"DingTalk inbound: {content} from {sender_name}")
            
            # Correct InboundMessage usage based on events.py definition
            # @dataclass class InboundMessage:
            # channel: str, sender_id: str, chat_id: str, content: str, ...
            msg = InboundMessage(
                channel=self.name,
                sender_id=sender_id,
                chat_id=sender_id, # For private stats, chat_id is sender_id
                content=str(content),
                metadata={
                    "sender_name": sender_name,
                    "platform": "dingtalk"
                }
            )
            await self.bus.publish_inbound(msg)
        except Exception as e:
            logger.error(f"Error publishing DingTalk message: {e}")
