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
import re
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
    mention_only_response: str = "Hi — what can I help with?"
    validate_inbound_auth: bool = False


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
        self._botframework_openid_config_url = (
            "https://login.botframework.com/v1/.well-known/openidconfiguration"
        )
        self._botframework_openid_config: dict[str, Any] | None = None
        self._botframework_openid_config_expires_at: float = 0.0
        self._botframework_jwks: dict[str, Any] | None = None
        self._botframework_jwks_expires_at: float = 0.0
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

                auth_header = self.headers.get("Authorization", "")
                if channel.config.validate_inbound_auth:
                    try:
                        fut = asyncio.run_coroutine_threadsafe(
                            channel._validate_inbound_auth(auth_header, payload),
                            channel._loop,
                        )
                        fut.result(timeout=15)
                    except Exception as e:
                        logger.warning("MSTeams inbound auth validation failed: {}", e)
                        self.send_response(401)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(b'{"error":"unauthorized"}')
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
        base_url = f"{ref.service_url.rstrip('/')}/v3/conversations/{ref.conversation_id}/activities"
        use_thread_reply = self.config.reply_in_thread and bool(ref.activity_id)
        url = (
            f"{base_url}/{ref.activity_id}"
            if use_thread_reply
            else base_url
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "type": "message",
            "text": msg.content or " ",
        }
        if use_thread_reply:
            payload["replyToId"] = ref.activity_id

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
        if not text:
            text = self.config.mention_only_response.strip()
            if not text:
                logger.debug("MSTeams ignoring empty message after mention stripping")
                return

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
        """Remove simple Teams mention markup from message text."""
        cleaned = re.sub(r"<at>.*?</at>", " ", text, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

<<<<<<< HEAD
=======
    def _log_inbound_auth_debug(self, auth_header: str) -> None:
        """Log sanitized inbound bearer token details for debugging."""
        if not auth_header.lower().startswith("bearer "):
            logger.info("MSTeams inbound auth debug bearer_present=False")
            return

        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            logger.info("MSTeams inbound auth debug bearer_present=True token_present=False")
            return

        try:
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
                algorithms=["RS256", "RS384", "RS512"],
            )
            logger.info(
                "MSTeams inbound auth debug kid={} alg={} iss={} aud={} azp={} appid={} serviceurl={} nbf={} exp={}",
                header.get("kid"),
                header.get("alg"),
                claims.get("iss"),
                claims.get("aud"),
                claims.get("azp"),
                claims.get("appid"),
                claims.get("serviceurl") or claims.get("serviceUrl"),
                claims.get("nbf"),
                claims.get("exp"),
            )
        except Exception as e:
            logger.warning("MSTeams inbound auth debug decode failed: {}", e)

    async def _validate_inbound_auth(self, auth_header: str, activity: dict[str, Any]) -> None:
        """Validate inbound Bot Framework bearer token."""
        if not auth_header.lower().startswith("bearer "):
            raise ValueError("missing bearer token")

        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            raise ValueError("empty bearer token")

        header = jwt.get_unverified_header(token)
        kid = str(header.get("kid") or "").strip()
        if not kid:
            raise ValueError("missing token kid")

        jwks = await self._get_botframework_jwks()
        keys = jwks.get("keys") or []
        jwk = next((key for key in keys if key.get("kid") == kid), None)
        if not jwk:
            raise ValueError(f"signing key not found for kid={kid}")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        claims = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=self.config.app_id,
            issuer="https://api.botframework.com",
            options={
                "require": ["exp", "nbf", "iss", "aud"],
            },
        )

        claim_service_url = str(
            claims.get("serviceurl") or claims.get("serviceUrl") or "",
        ).strip()
        activity_service_url = str(activity.get("serviceUrl") or "").strip()
        if claim_service_url and activity_service_url and claim_service_url != activity_service_url:
            raise ValueError("serviceUrl claim mismatch")

    async def _get_botframework_openid_config(self) -> dict[str, Any]:
        """Fetch and cache Bot Framework OpenID configuration."""
        import time

        now = time.time()
        if self._botframework_openid_config and now < self._botframework_openid_config_expires_at:
            return self._botframework_openid_config

        if not self._http:
            raise RuntimeError("MSTeams HTTP client not initialized")

        resp = await self._http.get(self._botframework_openid_config_url)
        resp.raise_for_status()
        self._botframework_openid_config = resp.json()
        self._botframework_openid_config_expires_at = now + 3600
        return self._botframework_openid_config

    async def _get_botframework_jwks(self) -> dict[str, Any]:
        """Fetch and cache Bot Framework JWKS."""
        import time

        now = time.time()
        if self._botframework_jwks and now < self._botframework_jwks_expires_at:
            return self._botframework_jwks

        if not self._http:
            raise RuntimeError("MSTeams HTTP client not initialized")

        openid_config = await self._get_botframework_openid_config()
        jwks_uri = str(openid_config.get("jwks_uri") or "").strip()
        if not jwks_uri:
            raise RuntimeError("Bot Framework OpenID config missing jwks_uri")

        resp = await self._http.get(jwks_uri)
        resp.raise_for_status()
        self._botframework_jwks = resp.json()
        self._botframework_jwks_expires_at = now + 3600
        return self._botframework_jwks

>>>>>>> 90b7a73 (Add opt-in Teams inbound auth validation)
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
