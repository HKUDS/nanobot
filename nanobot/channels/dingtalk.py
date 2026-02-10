"""DingTalk/DingDing channel implementation using Stream Mode."""

import asyncio
import json
import time
from typing import Any

from loguru import logger
import httpx

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DingTalkConfig

try:
    from dingtalk_stream import (
        DingTalkStreamClient,
        Credential,
        CallbackHandler,
        CallbackMessage,
        AckMessage,
    )
    from dingtalk_stream.chatbot import ChatbotMessage

    DINGTALK_AVAILABLE = True
except ImportError:
    DINGTALK_AVAILABLE = False
    # Fallback so class definitions don't crash at module level
    CallbackHandler = object  # type: ignore[assignment,misc]
    CallbackMessage = None  # type: ignore[assignment,misc]
    AckMessage = None  # type: ignore[assignment,misc]
    ChatbotMessage = None  # type: ignore[assignment,misc]


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

            # Check for different message types
            msg_type = getattr(chatbot_msg, "msgtype", None) or message.data.get("msgtype")
            content = ""
            media_paths = []
            
            if msg_type == "text":
                if chatbot_msg.text:
                    content = chatbot_msg.text.content.strip()
                if not content:
                    content = message.data.get("text", {}).get("content", "").strip()
            elif msg_type == "audio":
                # Audio message - check for downloadCode or url
                # message.data example: {"msgtype": "audio", "content": {"downloadCode": "..."}}
                audio_content = message.data.get("content", {})
                download_code = audio_content.get("downloadCode")
                
                if download_code:
                    try:
                        logger.info(f"Downloading DingTalk audio with code: {download_code}")
                        file_path = await self.channel._download_file(download_code)
                        
                        if file_path:
                            # Check if Groq key is configured
                            if not self.channel.groq_api_key:
                                logger.warning("Groq API key missing for DingTalk transcription")
                                content = "[Voice message: Transcription failed (Groq API Key missing)]"
                            else:
                                # Transcribe
                                from nanobot.providers.transcription import GroqTranscriptionProvider
                                transcriber = GroqTranscriptionProvider(api_key=self.channel.groq_api_key)
                                transcription = await transcriber.transcribe(file_path)
                                
                                if transcription:
                                    content = transcription
                                    logger.info(f"DingTalk voice transcribed: {content}")
                                else:
                                    logger.warning("DingTalk voice transcription failed (empty)")
                                    content = "[Voice message: Transcription failed]"
                        else:
                            logger.error("Failed to download DingTalk audio file")
                            content = "[Voice message: Download failed]"

                    except Exception as e:
                        logger.error(f"Error handling audio: {e}")
                        content = f"[Voice message error: {e}]"
            else:
                if chatbot_msg.text:
                    content = chatbot_msg.text.content.strip()

            if not content:
                logger.warning(
                    f"Received empty or unsupported message type: {msg_type}"
                )
                return AckMessage.STATUS_OK, "OK"

            sender_id = chatbot_msg.sender_staff_id or chatbot_msg.sender_id
            sender_name = chatbot_msg.sender_nick or "Unknown"

            logger.info(f"Received DingTalk message from {sender_name} ({sender_id}): {content}")

            # Forward to Nanobot via _on_message (non-blocking).
            # Store reference to prevent GC before task completes.
            task = asyncio.create_task(
                self.channel._on_message(content, sender_id, sender_name, is_voice=(msg_type == "audio"))
            )
            self.channel._background_tasks.add(task)
            task.add_done_callback(self.channel._background_tasks.discard)

            return AckMessage.STATUS_OK, "OK"

        except Exception as e:
            logger.error(f"Error processing DingTalk message: {e}")
            # Return OK to avoid retry loop from DingTalk server
            return AckMessage.STATUS_OK, "Error"


class DingTalkChannel(BaseChannel):
    """
    DingTalk channel using Stream Mode.

    Uses WebSocket to receive events via `dingtalk-stream` SDK.
    Uses direct HTTP API to send messages (SDK is mainly for receiving).

    Note: Currently only supports private (1:1) chat. Group messages are
    received but replies are sent back as private messages to the sender.
    """

    name = "dingtalk"

    name = "dingtalk"

    def __init__(
        self,
        config: DingTalkConfig,
        bus: MessageBus,
        groq_api_key: str = ""
    ):
        super().__init__(config, bus)
        self.config: DingTalkConfig = config
        self.groq_api_key = groq_api_key
        self._client: Any = None
        self._http: httpx.AsyncClient | None = None

        # Access Token management for sending messages
        self._access_token: str | None = None
        self._token_expiry: float = 0

        # Hold references to background tasks to prevent GC
        self._background_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Start the DingTalk bot with Stream Mode."""
        try:
            if not DINGTALK_AVAILABLE:
                logger.error(
                    "DingTalk Stream SDK not installed. Run: pip install dingtalk-stream"
                )
                return

            if not self.config.client_id or not self.config.client_secret:
                logger.error("DingTalk client_id and client_secret not configured")
                return

            self._running = True
            self._http = httpx.AsyncClient()

            logger.info(
                f"Initializing DingTalk Stream Client with Client ID: {self.config.client_id}..."
            )
            credential = Credential(self.config.client_id, self.config.client_secret)
            self._client = DingTalkStreamClient(credential)

            # Register standard handler
            handler = NanobotDingTalkHandler(self)
            self._client.register_callback_handler(ChatbotMessage.TOPIC, handler)

            logger.info("DingTalk bot started with Stream Mode")

            # client.start() is an async infinite loop handling the websocket connection
            await self._client.start()

        except Exception as e:
            logger.exception(f"Failed to start DingTalk channel: {e}")

    async def stop(self) -> None:
        """Stop the DingTalk bot."""
        self._running = False
        # Close the shared HTTP client
        if self._http:
            await self._http.aclose()
            self._http = None
        # Cancel outstanding background tasks
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    async def _get_access_token(self) -> str | None:
        """Get or refresh Access Token."""
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        data = {
            "appKey": self.config.client_id,
            "appSecret": self.config.client_secret,
        }

        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot refresh token")
            return None

        try:
            resp = await self._http.post(url, json=data)
            resp.raise_for_status()
            res_data = resp.json()
            self._access_token = res_data.get("accessToken")
            # Expire 60s early to be safe
            self._token_expiry = time.time() + int(res_data.get("expireIn", 7200)) - 60
            return self._access_token
        except Exception as e:
            logger.error(f"Failed to get DingTalk access token: {e}")
            return None

    async def _download_file(self, download_code: str, file_ext: str = ".mp3") -> str | None:
        """Download file using downloadCode."""
        token = await self._get_access_token()
        if not token:
            return None
            
        url = "https://api.dingtalk.com/v1.0/robot/messageFiles/download"
        headers = {
            "x-acs-dingtalk-access-token": token,
            "Content-Type": "application/json"
        }
        data = {
            "downloadCode": download_code,
            "robotCode": self.config.client_id
        }
        
        try:
            # 1. Get download URL
            resp = await self._http.post(url, json=data, headers=headers)
            resp.raise_for_status()
            download_url = resp.json().get("downloadUrl")
            
            if not download_url:
                logger.error("No downloadUrl returned from DingTalk")
                return None
                
            # 2. Download file content
            # Remove Authentication header for the actual file download usually?
            # The downloadUrl usually is a signed OSS URL.
            # We use a fresh client or just no headers.
            async with httpx.AsyncClient() as client:
                file_resp = await client.get(download_url)
                file_resp.raise_for_status()
                content = file_resp.content

            # 3. Save to temp file
            from pathlib import Path
            import uuid
            media_dir = Path.home() / ".nanobot" / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            file_path = media_dir / f"ding_{uuid.uuid4().hex[:8]}{file_ext}"
            
            with open(file_path, "wb") as f:
                f.write(content)
                
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Failed to download DingTalk file: {e}")
            return None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through DingTalk."""
        token = await self._get_access_token()
        if not token:
            return

        # oToMessages/batchSend: sends to individual users (private chat)
        # https://open.dingtalk.com/document/orgapp/robot-batch-send-messages
        url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"

        headers = {"x-acs-dingtalk-access-token": token}

        data = {
            "robotCode": self.config.client_id,
            "userIds": [msg.chat_id],  # chat_id is the user's staffId
            "msgKey": "sampleMarkdown",
            "msgParam": json.dumps({
                "text": msg.content,
                "title": "Nanobot Reply",
            }),
        }

        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot send")
            return

        try:
            # Check for voice message
            if msg.metadata and msg.metadata.get("voice_file"):
                voice_path = msg.metadata["voice_file"]
                try:
                    # 1. Upload to DingTalk
                    with open(voice_path, "rb") as f:
                        # Ensure we read the file content
                        content = f.read()
                        media_id = self._client.upload_to_dingtalk(
                            content,
                            filetype="voice",
                            filename="voice.mp3",
                            mimetype="audio/mpeg"
                        )
                    
                    if media_id:
                        # 2. Send voice message
                        voice_data = {
                            "robotCode": self.config.client_id,
                            "userIds": [msg.chat_id],
                            "msgKey": "sampleAudio",
                            "msgParam": json.dumps({
                                "mediaId": media_id,
                                "duration": "10",  # Approximation
                            }),
                        }
                        resp = await self._http.post(url, json=voice_data, headers=headers)
                        if resp.status_code != 200:
                            logger.error(f"DingTalk voice send failed: {resp.text}")
                        else:
                            logger.debug(f"DingTalk voice sent to {msg.chat_id}")
                        
                        # Continue to send text message as transcript/fallback
                        
                except Exception as e:
                    logger.error(f"Failed to send DingTalk voice, falling back to text: {e}")

            # Fallback to text/markdown
            resp = await self._http.post(url, json=data, headers=headers)
            if resp.status_code != 200:
                logger.error(f"DingTalk send failed: {resp.text}")
            else:
                logger.debug(f"DingTalk message sent to {msg.chat_id}")
        except Exception as e:
            logger.error(f"Error sending DingTalk message: {e}")

    async def _on_message(self, content: str, sender_id: str, sender_name: str, is_voice: bool = False) -> None:
        """Handle incoming message (called by NanobotDingTalkHandler).

        Delegates to BaseChannel._handle_message() which enforces allow_from
        permission checks before publishing to the bus.
        """
        try:
            logger.info(f"DingTalk inbound: {content} from {sender_name}")
            
            await self._handle_message(
                sender_id=sender_id,
                chat_id=sender_id,  # For private chat, chat_id == sender_id
                content=str(content),
                metadata={
                    "sender_name": sender_name,
                    "platform": "dingtalk",
                    "is_voice": is_voice,
                },
            )
        except Exception as e:
            logger.error(f"Error publishing DingTalk message: {e}")
