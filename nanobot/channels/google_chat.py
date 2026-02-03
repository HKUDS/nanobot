import asyncio
import json
from loguru import logger
from typing import Any
import httpx
import google.auth.transport
from google.oauth2 import service_account
from aiohttp import web

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import GoogleChatConfig


class HttpxResponse:
    """A wrapper to make httpx responses compatible with google-auth."""

    def __init__(self, response: httpx.Response):
        self.status = response.status_code
        self.headers = response.headers
        self.data = response.content


class AsyncHttpxTransport(google.auth.transport.Request):
    """Adapter for google.auth to use httpx."""

    def __init__(self, client: httpx.Client):
        self.client = client

    def __call__(
        self, url, method="GET", body=None, headers=None, timeout=None, **kwargs
    ):
        response = self.client.request(
            method, url, content=body, headers=headers, timeout=timeout, **kwargs
        )
        return HttpxResponse(response)


class GoogleChatChannel(BaseChannel):
    name = "google_chat"

    def __init__(self, config: GoogleChatConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: GoogleChatConfig = config
        self.credentials = None
        self._site = None
        self._runner = None

    async def start(self) -> None:
        if not self.config.port:
            logger.error("Google Chat: port not configured")
            return
        try:
            if self.config.credentials_file:
                self.credentials = (
                    service_account.Credentials.from_service_account_file(
                        self.config.credentials_file,
                        scopes=["https://www.googleapis.com/auth/chat.bot"],
                    )
                )
            app = web.Application()
            path = self.config.path or "/google_chat"
            app.router.add_post(path, self._handle_webhook)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", self.config.port)
            await site.start()
            self._runner, self._site, self._running = runner, site, True
            logger.info(
                f"Google Chat webhook listening on port {self.config.port} at {path}"
            )
            while self._running:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Failed to start Google Chat channel: {e}")

    async def stop(self) -> None:
        self._running = False
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            asyncio.create_task(self._process_message(data))
            return web.json_response({})
        except Exception as e:
            logger.error(f"Error handling webhook: {e}")
            return web.Response(status=500)

    async def send(self, msg: OutboundMessage) -> None:
        if not self.credentials:
            logger.error("Google Chat: Cannot send message, no credentials")
            return
        try:

            def refresh_token():
                with httpx.Client() as client:
                    request = AsyncHttpxTransport(client)
                    self.credentials.refresh(request)
                    return self.credentials.token

            loop = asyncio.get_running_loop()
            token = await loop.run_in_executor(None, refresh_token)
            url = f"https://chat.googleapis.com/v1/{msg.chat_id}/messages"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, json={"text": msg.content}, headers=headers
                )
                response.raise_for_status()
        except Exception as e:
            logger.error(f"Error sending to Google Chat: {e}")

    async def _process_message(self, data: dict[str, Any]) -> None:
        """Process a Google Chat event with robust schema detection."""
        try:
            logger.debug(f"FULL DATA: {json.dumps(data)}")
            chat_data = data.get("chat", {})

            # Detect Event Type
            event_type = data.get("type")
            if not event_type:
                if "messagePayload" in chat_data:
                    event_type = "MESSAGE"
                elif "addedToSpacePayload" in chat_data:
                    event_type = "ADDED_TO_SPACE"

            logger.debug(f"Processing Google Chat event: {event_type}")

            if event_type == "MESSAGE":
                await self._handle_chat_message(data)
            elif event_type == "ADDED_TO_SPACE":
                await self._handle_added_to_space(data)
        except Exception as e:
            logger.error(f"Error processing Google Chat event: {e}")

    async def _handle_chat_message(self, data: dict[str, Any]) -> None:
        chat_data = data.get("chat", {})
        payload = chat_data.get("messagePayload", {})

        msg_data = data.get("message") or payload.get("message") or {}
        space_data = (
            data.get("space") or payload.get("space") or chat_data.get("space") or {}
        )
        user_data = chat_data.get("user") or msg_data.get("sender") or {}

        sender_id = str(user_data.get("email") or user_data.get("name"))
        chat_id = str(space_data.get("name"))
        text = str(msg_data.get("text", ""))

        if text:
            logger.info(f"Message from {sender_id} in {chat_id}: {text}")
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=text,
                metadata={
                    "event_type": "MESSAGE",
                    "sender_name": user_data.get("displayName"),
                },
            )

    async def _handle_added_to_space(self, data: dict[str, Any]) -> None:
        chat_data = data.get("chat", {})
        payload = chat_data.get("addedToSpacePayload", {})
        space_data = (
            data.get("space") or payload.get("space") or chat_data.get("space") or {}
        )

        chat_id = space_data.get("name")
        if chat_id:
            logger.info(f"Bot added to space: {chat_id}")
            await self.send(
                OutboundMessage(
                    channel=self.name,
                    chat_id=chat_id,
                    content="Hello! I am nanobot. Thanks for adding me!",
                )
            )
