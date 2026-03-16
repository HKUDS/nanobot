"""Microsoft Teams channel MVP using a tiny built-in HTTP webhook server.

Scope:
- DM-focused MVP
- text inbound/outbound
- conversation reference persistence
- sender allowlist support
- no attachments/cards/polls yet
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_workspace_path
from nanobot.config.schema import Base


class MSTeamsConfig(Base):
    """Microsoft Teams channel configuration."""

    enabled: bool = False
    app_id: str = ""
    app_password: str = ""
    tenant_id: str = ""
    host: str = "0.0.0.0"
    port: int = 3978
    path: str = "/api/messages"
    allow_from: list[str] = Field(default_factory=list)
    reply_in_thread: bool = True


@dataclass
class ConversationRef:
    """Minimal stored conversation reference for replies."""

    service_url: str
    conversation_id: str
    bot_id: str | None = None
    activity_id: str | None = None
    conversation_type: str | None = None
    tenant_id: str | None = None


class MSTeamsChannel(BaseChannel):
    """Microsoft Teams channel (DM-first MVP)."""

    name = "msteams"
    display_name = "Microsoft Teams"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MSTeamsConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = MSTeamsConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: MSTeamsConfig = config
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._http: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._refs_path = get_workspace_path() / "state" / "msteams_conversations.json"
        self._refs_path.parent.mkdir(parents=True, exist_ok=True)
        self._conversation_refs: dict[str, ConversationRef] = self._load_refs()

    async def start(self) -> None:
        """Start the Teams webhook listener."""
        if not self.config.app_id or not self.config.app_password:
            logger.error("MSTeams app_id/app_password not configured")
            return

        self._loop = asyncio.get_running_loop()
        self._http = httpx.AsyncClient(timeout=30.0)
        self._running = True

        channel = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                if self.path != channel.config.path:
                    self.send_response(404)
                    self.end_headers()
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    payload = json.loads(raw.decode("utf-8"))
                except Exception as e:
                    logger.warning("MSTeams invalid request body: {}", e)
                    self.send_response(400)
                    self.end_headers()
                    return

                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        channel._handle_activity(payload),
                        channel._loop,
                    )
                    fut.result(timeout=15)
                except Exception as e:
                    logger.warning("MSTeams activity handling failed: {}", e)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format: str, *args: Any) -> None:
                return

        self._server = ThreadingHTTPServer((self.config.host, self.config.port), Handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="nanobot-msteams",
            daemon=True,
        )
        self._server_thread.start()

        logger.info(
            "MSTeams webhook listening on http://{}:{}{}",
            self.config.host,
            self.config.port,
            self.config.path,
        )

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the channel."""
        self._running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=2)
        self._server_thread = None
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a plain text reply into an existing Teams conversation."""
        if not self._http:
            logger.warning("MSTeams HTTP client not initialized")
            return

        ref = self._conversation_refs.get(str(msg.chat_id))
        if not ref:
            logger.warning("MSTeams conversation ref not found for chat_id={}", msg.chat_id)
            return

        token = await self._get_access_token()
        url = f"{ref.service_url.rstrip('/')}/v3/conversations/{ref.conversation_id}/activities"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "type": "message",
            "text": msg.content or " ",
        }

        try:
            resp = await self._http.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            logger.info("MSTeams message sent to {}", ref.conversation_id)
        except Exception as e:
            logger.error("MSTeams send failed: {}", e)

    async def _handle_activity(self, activity: dict[str, Any]) -> None:
        """Handle inbound Teams/Bot Framework activity."""
        if activity.get("type") != "message":
            return

        conversation = activity.get("conversation") or {}
        from_user = activity.get("from") or {}
        recipient = activity.get("recipient") or {}
        channel_data = activity.get("channelData") or {}

        sender_id = str(from_user.get("aadObjectId") or from_user.get("id") or "").strip()
        conversation_id = str(conversation.get("id") or "").strip()
        text = str(activity.get("text") or "").strip()
        service_url = str(activity.get("serviceUrl") or "").strip()
        activity_id = str(activity.get("id") or "").strip()
        conversation_type = str(conversation.get("conversationType") or "").strip()

        if not sender_id or not conversation_id or not service_url:
            return

        if recipient.get("id") and from_user.get("id") == recipient.get("id"):
            return

        # DM-only MVP: ignore group/channel traffic for now
        if conversation_type and conversation_type not in ("personal", ""):
            logger.debug("MSTeams ignoring non-DM conversation {}", conversation_type)
            return

        if not self.is_allowed(sender_id):
            return

        text = self._strip_possible_bot_mention(text)

        self._conversation_refs[conversation_id] = ConversationRef(
            service_url=service_url,
            conversation_id=conversation_id,
            bot_id=str(recipient.get("id") or "") or None,
            activity_id=activity_id or None,
            conversation_type=conversation_type or None,
            tenant_id=str((channel_data.get("tenant") or {}).get("id") or "") or None,
        )
        self._save_refs()

        await self._handle_message(
            sender_id=sender_id,
            chat_id=conversation_id,
            content=text,
            metadata={
                "msteams": {
                    "activity_id": activity_id,
                    "conversation_id": conversation_id,
                    "conversation_type": conversation_type or "personal",
                    "from_name": from_user.get("name"),
                }
            },
        )

    def _strip_possible_bot_mention(self, text: str) -> str:
        """Very small MVP cleanup for Teams mention markup."""
        return text.replace("<at>nanobot</at>", "").strip()

    def _load_refs(self) -> dict[str, ConversationRef]:
        """Load stored conversation references."""
        if not self._refs_path.exists():
            return {}
        try:
            data = json.loads(self._refs_path.read_text(encoding="utf-8"))
            out: dict[str, ConversationRef] = {}
            for key, value in data.items():
                out[key] = ConversationRef(**value)
            return out
        except Exception as e:
            logger.warning("Failed to load MSTeams conversation refs: {}", e)
            return {}

    def _save_refs(self) -> None:
        """Persist conversation references."""
        try:
            data = {
                key: {
                    "service_url": ref.service_url,
                    "conversation_id": ref.conversation_id,
                    "bot_id": ref.bot_id,
                    "activity_id": ref.activity_id,
                    "conversation_type": ref.conversation_type,
                    "tenant_id": ref.tenant_id,
                }
                for key, ref in self._conversation_refs.items()
            }
            self._refs_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to save MSTeams conversation refs: {}", e)

    async def _get_access_token(self) -> str:
        """Fetch an access token for Bot Framework / Azure Bot auth."""
        import time

        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        if not self._http:
            raise RuntimeError("MSTeams HTTP client not initialized")

        tenant = (self.config.tenant_id or "").strip() or "botframework.com"
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.config.app_id,
            "client_secret": self.config.app_password,
            "scope": "https://api.botframework.com/.default",
        }
        resp = await self._http.post(token_url, data=data)
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = now + int(payload.get("expires_in", 3600))
        return self._token
